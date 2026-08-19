"""
agent/copilot_agent.py — CopilotAgent: Structured Reasoning Architecture.

Triển khai AWS Bedrock (Amazon Nova) làm LLM backend.
6-layer pipeline: Intent Parser -> Planner -> Executor -> Evidence Aggregator -> Answer Generator -> Guard.
"""

import os
import json
import uuid
import time
import hashlib
import logging
import contextvars
import re
from typing import Dict, Any, List, Optional

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage

from src.telemetry import trace_llm_ctx, get_tracer

from src.guardrails import (
    rate_limiter,
    check_input,
    check_input_bedrock,
    sanitize_pii_from_input,
    validate_tool_call,
    request_confirmation,
    verify_confirmation_token,
    filter_output,
    with_fallback,
    MaxIterationsExceeded,
    MAX_TOOL_ITERATIONS,
)
from src.guardrails.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitBreakerConfig,
)
from src.guardrails.retry import retry_with_backoff, RetryConfig
from src.guardrails.schema_validator import (
    validate_intent_parser_output,
    validate_planner_output,
    validate_synthesis_output,
    repair_intent_fallback,
    repair_plan_fallback,
)
from src.memory import SessionStore, CacheStore
from src.tools import all_shopping_tools
from src.tools.catalog_tool import (
    get_all_products,
    get_categories,
    get_top_rated_products,
)
from src.llm.prompt import SYSTEM_PROMPT, INTENT_PARSE_PROMPT, EVIDENCE_SYNTHESIS_PROMPT

logger = logging.getLogger("agent.copilot_agent")
PRODUCT_ID_PATTERN = re.compile(r"^[A-Z0-9]{8,12}$")

TOOLS_MAP: Dict[str, Any] = {t.name: t for t in all_shopping_tools}


def _now_ms() -> int:
    return int(time.time() * 1000)


class CopilotAgent:
    def __init__(self):
        self._sessions = SessionStore()
        self._cache = CacheStore()
        self.llm = self._build_llm()
        self._steps: List[Dict[str, Any]] = []

        # ── MANDATE #25: Resilience Components ──
        # Circuit breaker for Bedrock provider (5 failures → open, 60s recovery timeout, 2 successes to close)
        self._bedrock_breaker = CircuitBreaker(
            "bedrock",
            CircuitBreakerConfig(
                failure_threshold=5, recovery_timeout=60, success_threshold=2
            ),
        )
        # Retry config for transient failures (max 3 retries, exponential backoff 1-8s)
        self._retry_config = RetryConfig(
            max_retries=3, initial_delay_ms=1000, max_delay_ms=8000
        )

        # ── MANDATE #23: GenAI Cache + Long-term Memory ──
        from src.memory.genai_cache import get_genai_cache_store
        from src.memory.longterm_memory import get_longterm_memory_store

        self._genai_cache = get_genai_cache_store()
        self._longterm_memory = get_longterm_memory_store()

    def _build_llm(self):
        model = os.getenv("BEDROCK_MODEL_ID")
        region = os.getenv("BEDROCK_REGION")
        fallback_model = os.getenv("BEDROCK_FALLBACK_MODEL_ID")

        try:
            self.llm = ChatBedrockConverse(
                model=model,
                region_name=region,
                temperature=0.1,
                max_tokens=2048,
            )
            logger.info(f"[AGENT] Primary LLM initialized: {model}")
        except Exception as e:
            logger.error(f"[AGENT] Cannot init Primary Bedrock LLM ({model}): {e}")
            self.llm = None

        if fallback_model and fallback_model != model:
            try:
                self.fallback_llm = ChatBedrockConverse(
                    model=fallback_model,
                    region_name=region,
                    temperature=0.1,
                    max_tokens=2048,
                )
                logger.info(f"[AGENT] Secondary Fallback LLM initialized: {fallback_model}")
            except Exception as e:
                logger.warning(f"[AGENT] Cannot init Secondary Fallback LLM ({fallback_model}): {e}")
                self.fallback_llm = None
        else:
            self.fallback_llm = None

        return self.llm

    def _time(self, action: str) -> tuple:
        return _now_ms(), action

    def _emit_trace(self, step: str, detail: str, status: str = "RUNNING", duration_ms: Optional[int] = None):
        trace_obj = {
            "step": step,
            "detail": detail,
            "status": status,
            "timestamp": time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        }
        if duration_ms is not None:
            trace_obj["duration_ms"] = duration_ms
        if hasattr(self, "_on_trace_callback") and self._on_trace_callback:
            try:
                self._on_trace_callback(trace_obj)
            except Exception:
                pass

    def _end(self, start: int, action: str, status: str, detail: str):
        dur = _now_ms() - start
        step_info = {
            "action": action,
            "status": status,
            "detail": detail,
            "duration_ms": dur,
        }
        self._steps.append(step_info)
        self._emit_trace(action.lower(), detail, status=status, duration_ms=dur)

    async def _call_llm(self, messages: list, **kwargs):
        ctx = trace_llm_ctx.get()
        if ctx is None:
            if self.llm:
                try:
                    return await self.llm.ainvoke(messages, **kwargs)
                except Exception as e:
                    if hasattr(self, "fallback_llm") and self.fallback_llm:
                        return await self.fallback_llm.ainvoke(messages, **kwargs)
                    raise
            elif hasattr(self, "fallback_llm") and self.fallback_llm:
                return await self.fallback_llm.ainvoke(messages, **kwargs)
            else:
                raise RuntimeError("No LLM available")

        prompt_text = " ".join(m.content for m in messages if hasattr(m, "content"))
        trace_id = str(uuid.uuid4())
        t0 = time.time()
        try:
            response = await self.llm.ainvoke(messages, **kwargs)
            latency_ms = int((time.time() - t0) * 1000)
            get_tracer().record_call(
                trace_id=trace_id,
                request_id=ctx["request_id"],
                layer=ctx["layer"],
                session_id=ctx.get("session_id", ""),
                user_id=ctx.get("user_id", ""),
                prompt_text=prompt_text,
                response=response,
                outcome="ok",
                latency_ms=latency_ms,
            )
            return response
        except Exception as primary_err:
            if hasattr(self, "fallback_llm") and self.fallback_llm is not None:
                try:
                    logger.warning(
                        f"[AGENT] Primary LLM failed ({primary_err}). Attempting Secondary Fallback Model..."
                    )
                    response = await self.fallback_llm.ainvoke(messages, **kwargs)
                    latency_ms = int((time.time() - t0) * 1000)
                    get_tracer().record_call(
                        trace_id=trace_id,
                        request_id=ctx["request_id"],
                        layer=ctx["layer"],
                        session_id=ctx.get("session_id", ""),
                        user_id=ctx.get("user_id", ""),
                        prompt_text=prompt_text,
                        response=response,
                        outcome="fallback",
                        error=f"Primary model failed ({primary_err}), used secondary model",
                        latency_ms=latency_ms,
                    )
                    return response
                except Exception as secondary_err:
                    logger.error(
                        f"[AGENT] Secondary Fallback LLM also failed: {secondary_err}"
                    )

            latency_ms = int((time.time() - t0) * 1000)
            get_tracer().record_call(
                trace_id=trace_id,
                request_id=ctx["request_id"],
                layer=ctx["layer"],
                session_id=ctx.get("session_id", ""),
                user_id=ctx.get("user_id", ""),
                prompt_text=prompt_text,
                response=None,
                error=str(primary_err),
                outcome="error",
                latency_ms=latency_ms,
            )
            raise primary_err

    def _extract_text(self, response: Any) -> str:
        final = response.content if hasattr(response, "content") else str(response)
        if isinstance(final, list):
            text_parts = []
            for part in final:
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
                elif isinstance(part, str):
                    text_parts.append(part)
                elif hasattr(part, "text"):
                    text_parts.append(part.text)
            final = "".join(text_parts)
        return final or ""

    # LAYER 1: Intent Parser (with retry, circuit-breaker, schema validation)
    async def _parse_intent_with_llm(self, user_message: str, session: dict) -> dict:
        if not self.llm:
            # Fallback keyword logic if LLM is down
            logger.warning(
                "[INTENT] LLM is None, using keyword-based heuristic fallback"
            )
            lower = user_message.lower()
            if "cart" in lower or "giỏ hàng" in lower:
                if "add" in lower or "thêm" in lower:
                    return {
                        "task_type": "add_to_cart",
                        "target_entity": "cart",
                        "context_reference": "this",
                    }
                return {"task_type": "view_cart", "target_entity": "cart"}
            if "review" in lower or "đánh giá" in lower:
                if "highest" in lower or "best" in lower or "cao nhất" in lower:
                    return {
                        "task_type": "rank",
                        "target_entity": "product",
                        "ranking_by": "review_score",
                    }
                return {"task_type": "get_reviews", "target_entity": "review"}
            if "category" in lower or "danh mục" in lower:
                return {"task_type": "list_categories", "target_entity": "category"}
            if "all products" in lower or "tất cả sản phẩm" in lower:
                return {"task_type": "list_products", "target_entity": "product"}
            return {
                "task_type": "search",
                "target_entity": "product",
                "product_query": user_message,
            }

        context = session.get("context", {})

        # FIX #3: Use a shallow copy to avoid mutating the session's context dict
        context_for_prompt = dict(context)
        if "last_search_results" in context_for_prompt:
            context_for_prompt["_display_list"] = [
                f"{i+1}. {p.get('name')}"
                for i, p in enumerate(context_for_prompt["last_search_results"])
            ]

        context_str = json.dumps(context_for_prompt, ensure_ascii=False)
        chat_history = self._sessions.get_recent_history_str(
            session.get("session_id", "")
        )

        # ── MANDATE #23: Inject Long-term Memory into Prompt ──
        user_id = session.get("user_id", "anonymous")
        longterm_context = self._longterm_memory.get_context_summary(user_id)
        if longterm_context:
            chat_history = f"{longterm_context}\n\n{chat_history}"

        prompt = INTENT_PARSE_PROMPT.format(
            chat_history=chat_history, context=context_str, user_message=user_message
        )

        # ── Check Cache for Intent Parser ──
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cache_key = f"intent:{prompt_hash}"
        cached_intent = self._cache.get_raw(cache_key)
        if cached_intent is not None:
            logger.debug("[INTENT] Cache HIT")
            return cached_intent

        # ── MANDATE #25: Resilient LLM call with retry + circuit-breaker + schema validation ──
        try:
            # Check if circuit breaker is open (fast-fail)
            if self._bedrock_breaker.is_open:
                logger.warning(
                    "[INTENT] Circuit breaker is OPEN for Bedrock, using fallback"
                )
                return repair_intent_fallback(user_message)

            # Call with retry on transient failures
            async def _call_intent_parser():
                response = await self._call_llm([HumanMessage(content=prompt)])
                return self._extract_text(response)

            text = await retry_with_backoff(
                _call_intent_parser, config=self._retry_config
            )

            # Validate & repair schema
            validation = validate_intent_parser_output(text)
            if validation.is_valid:
                parsed_intent = validation.data
                # Mark that we used LLM (not fallback)
                parsed_intent["_model_source"] = "llm"
            else:
                logger.warning(
                    f"[INTENT] Schema validation failed: {validation.error}. Using fallback."
                )
                parsed_intent = repair_intent_fallback(text)
                parsed_intent["_model_source"] = "repaired"

            # Cache for 10 minutes
            self._cache.set_raw(cache_key, parsed_intent, ttl=600)
            return parsed_intent

        except Exception as e:
            logger.error(
                f"[INTENT] Fatal error in intent parsing: {e}. Using fallback."
            )
            return repair_intent_fallback(user_message)

    # Structured context resolution — trusts LLM's context_reference & ordinal_index
    def _resolve_context_references(self, intent: dict, session: dict) -> dict:
        context = session.get("context", {})
        last_results = context.get("last_search_results", [])
        ref = intent.get("context_reference", "none")
        ordinal = intent.get("ordinal_index")

        # Task types with their own action semantics — resolving to a product must
        # NOT re-route them to a price lookup.
        _action_tasks = {
            "add_to_cart",
            "get_reviews",
            "get_recommendations",
            "compare",
            "rank",
            "unsupported_cart_action",
        }

        ref = intent.get("context_reference", "none")
        ordinal = intent.get("ordinal_index")

        # Override ref to 'both' if user explicitly says 'cả hai' / 'cả 2' / 'ca hai'
        raw_msg = ""
        msgs = session.get("messages", [])
        if msgs:
            raw_msg = (msgs[-1].get("content") or "").lower()
        if any(kw in raw_msg for kw in ["cả hai", "cả 2", "ca hai"]):
            ref = "both"
            intent["context_reference"] = "both"

        # ── "both"/"cả hai"/"these" — resolve the two most recent products ──
        if ref in ["both", "these", "those"]:
            # Priority: check _multi_search_tops accumulated from compare search steps
            # (each search in a compare plan deposits its top-1 here, so both products survive)
            multi_tops = context.get("_multi_search_tops", [])
            source_list = multi_tops if len(multi_tops) >= 2 else last_results
            if len(source_list) >= 2:
                intent["product_name"] = source_list[0].get("name", "")
                intent["product_name_2"] = source_list[1].get("name", "")
                intent["product_id"] = source_list[0].get("id", "")
                intent["product_id_2"] = source_list[1].get("id", "")
                logger.info(
                    f"[CONTEXT] Resolved 'both' to: {intent['product_name']}, {intent['product_name_2']}"
                )
                return intent
            # Referenced two items but there is no prior context → ask, don't error.
            intent["needs_clarification"] = True
            intent["clarification_question"] = (
                "Bạn muốn thao tác với hai sản phẩm nào? Vui lòng tìm kiếm hoặc "
                "nêu rõ tên sản phẩm giúp mình nhé."
            )
            return intent

        # ── Ordinal reference ("thứ nhất"/"first"/"2nd"...) ──
        if ordinal and isinstance(ordinal, int) and ordinal >= 1:
            if ordinal <= len(last_results):
                product = last_results[ordinal - 1]
                intent["product_name"] = product.get("name", "")
                intent["product_id"] = product.get("id", "")
                # Re-ground the answer: force a fresh lookup so price/specs come
                # from real evidence (prevents hallucinated prices, e.g. TC_CTX_001).
                if intent.get("task_type") not in _action_tasks:
                    intent["task_type"] = "lookup"
                logger.info(
                    f"[CONTEXT] Resolved ordinal #{ordinal} to: {intent['product_name']}"
                )
                return intent
            # Ordinal given but nothing to index into → clarify.
            intent["needs_clarification"] = True
            intent["clarification_question"] = (
                "Mình chưa có danh sách sản phẩm nào trước đó để chọn. "
                "Bạn vui lòng tìm kiếm sản phẩm trước nhé."
            )
            return intent

        # ── Pronoun reference ("it"/"that"/"đó"/"cái đó") ──
        if ref in [
            "this",
            "that",
            "it",
            "previous",
            "last",
            "đó",
            "nó",
            "cái này",
            "cái đó",
        ]:
            resolved = False
            # Prefer fuzzy-matching an explicit product_name against last results.
            raw_pname = intent.get("product_name")
            if isinstance(raw_pname, list):
                raw_pname = " ".join(str(x) for x in raw_pname)
            pname = (raw_pname or "").lower()
            if pname and not intent.get("product_id"):
                for p in last_results:
                    db_name = (p.get("name") or "").lower()
                    if db_name and (db_name in pname or pname in db_name):
                        intent["product_id"] = p.get("id")
                        intent["product_name"] = p.get("name")
                        resolved = True
                        break

            if not resolved and context.get("last_product_id"):
                intent["product_id"] = context["last_product_id"]
                intent["product_name"] = context.get("last_product_name", "")
                resolved = True

            if resolved:
                if intent.get("task_type") not in _action_tasks:
                    intent["task_type"] = "lookup"
                logger.info(
                    f"[CONTEXT] Resolved '{ref}' to: {intent.get('product_name')}"
                )
                return intent

            # Nothing in context to bind the pronoun to → clarify instead of guessing
            # (TC_CTX_002: "Cái đó bao nhiêu tiền?" with no prior turn).
            intent["needs_clarification"] = True
            intent["clarification_question"] = (
                "Bạn đang hỏi về sản phẩm nào ạ? Vui lòng nêu rõ tên sản phẩm "
                "hoặc tìm kiếm trước giúp mình nhé."
            )
            return intent

        # No explicit context reference — still try to normalize a product_name
        # against the last search results if one was mentioned.
        pname = (intent.get("product_name") or "").lower()
        if pname and not intent.get("product_id") and last_results:
            for p in last_results:
                db_name = (p.get("name") or "").lower()
                if db_name and (db_name in pname or pname in db_name):
                    intent["product_id"] = p.get("id")
                    intent["product_name"] = p.get("name")
                    break

        return intent

    # LAYER 2: LLM-driven Planner with Rule-based Fallback (with resilience)
    async def _build_plan_with_llm(
        self, intent: dict, user_id: str, session: dict
    ) -> List[dict]:
        task_type = intent.get("task_type", "unknown")
        if task_type in ["greeting", "unknown", "unsupported_cart_action", "clarify"]:
            return []

        # First, try the deterministic Heuristic Planner (always works, no LLM dependency)
        heuristic_plan = self._build_plan_from_intent(intent, user_id)
        if heuristic_plan:
            logger.info(
                f"[PLANNER] Using heuristic plan with {len(heuristic_plan)} steps for {task_type}"
            )
            return heuristic_plan

        # Fallback to LLM Planner only if heuristic planner produced no plan
        # ── MANDATE #25: Resilient LLM plan generation with circuit-breaker + retry + validation ──
        if self.llm:
            try:
                from src.llm.prompt import LLM_PLANNER_PROMPT

                # Check circuit breaker first (fast-fail if Bedrock is broken)
                if self._bedrock_breaker.is_open:
                    logger.warning(
                        "[PLANNER] Circuit breaker OPEN, skipping LLM, returning empty plan"
                    )
                    return []

                ctx_dict = session.get("context", {})
                ctx_summary = {
                    "last_product_id": ctx_dict.get("last_product_id"),
                    "last_product_name": ctx_dict.get("last_product_name"),
                    "last_search_count": len(ctx_dict.get("last_search_results", [])),
                    "_display_list": ctx_dict.get("_display_list", []),
                }
                prompt = LLM_PLANNER_PROMPT.format(
                    context_json=json.dumps(ctx_summary, ensure_ascii=False),
                    intent_json=json.dumps(intent, ensure_ascii=False),
                    user_id=user_id,
                )

                # Call with retry + circuit breaker protection
                async def _call_planner():
                    response = await self._call_llm([HumanMessage(content=prompt)])
                    return self._extract_text(response)

                text = await retry_with_backoff(
                    _call_planner, config=self._retry_config
                )
                text = text.strip()

                # Extract JSON (handle markdown blocks)
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0]

                # ── Schema validation: ensure plan is valid before using ──
                validation = validate_planner_output(text)
                if not validation.is_valid:
                    logger.warning(
                        f"[PLANNER] Schema validation failed: {validation.error}. Falling back to empty plan."
                    )
                    return repair_plan_fallback()

                plan = validation.data

                # Validate tool names and structure
                valid_tools = set(TOOLS_MAP.keys()).union(
                    {"__fetch_reviews_for_context__"}
                )
                if isinstance(plan, list) and len(plan) <= 6:
                    if all(
                        isinstance(step, dict) and step.get("name") in valid_tools
                        for step in plan
                    ):
                        logger.info(
                            f"[PLANNER] LLM generated plan with {len(plan)} steps"
                        )
                        return plan
                    else:
                        logger.warning(
                            "[PLANNER] Plan contains invalid tool names, using empty plan"
                        )
                        return repair_plan_fallback()
                else:
                    logger.warning(
                        "[PLANNER] Plan validation failed (not list or too many steps)"
                    )
                    return repair_plan_fallback()

            except Exception as e:
                logger.warning(
                    f"[PLANNER] LLM plan generation failed ({e}), using empty plan"
                )
                return repair_plan_fallback()

        return []

    # LAYER 2 (Fallback): Generic Rule-based Planner
    def _build_plan_from_intent(self, intent: dict, user_id: str) -> List[dict]:
        task_type = intent.get("task_type", "unknown")
        plan = []

        if task_type == "add_to_cart":
            pid = intent.get("product_id")
            pname = intent.get("product_name") or intent.get("product_query")
            qty = intent.get("quantity", 1)
            if pid:
                plan.append(
                    {
                        "name": "add_to_cart_tool",
                        "args": {
                            "user_id": user_id,
                            "product_id": pid,
                            "quantity": qty,
                        },
                    }
                )
            elif pname and PRODUCT_ID_PATTERN.match(str(pname).strip().upper()):
                plan.append(
                    {
                        "name": "add_to_cart_tool",
                        "args": {
                            "user_id": user_id,
                            "product_id": str(pname).strip().upper(),
                            "quantity": qty,
                        },
                    }
                )
            elif pname:
                plan.append({"name": "get_product_id", "args": {"product_name": pname}})
                plan.append(
                    {
                        "name": "add_to_cart_tool",
                        "args": {
                            "user_id": user_id,
                            "product_id": "$PREV",
                            "quantity": qty,
                        },
                    }
                )
            else:
                plan.append(
                    {
                        "name": "add_to_cart_tool",
                        "args": {
                            "user_id": user_id,
                            "product_id": "$CTX",
                            "quantity": qty,
                        },
                    }
                )

            # "both"/"cả hai": a second product was resolved from context
            # (see _resolve_context_references) — add it too so we don't silently
            # drop the second item (TC_HARD_004).
            pid2 = intent.get("product_id_2")
            if pid2:
                plan.append(
                    {
                        "name": "add_to_cart_tool",
                        "args": {
                            "user_id": user_id,
                            "product_id": pid2,
                            "quantity": qty,
                        },
                    }
                )
        elif task_type == "view_cart":
            plan.append({"name": "get_cart_tool", "args": {"user_id": user_id}})
        elif task_type == "get_reviews":
            pname = intent.get("product_name")
            pid = intent.get("product_id")
            if pid:
                plan.append(
                    {"name": "get_product_reviews_tool", "args": {"product_id": pid}}
                )
            elif pname:
                plan.append({"name": "get_product_id", "args": {"product_name": pname}})
                plan.append(
                    {
                        "name": "get_product_reviews_tool",
                        "args": {"product_id": "$PREV"},
                    }
                )
            else:
                plan.append({"name": "__fetch_reviews_for_context__", "args": {}})
        elif task_type == "lookup":
            pname = intent.get("product_name") or intent.get("product_query", "")
            if pname:
                plan.append({"name": "search_products_v2", "args": {"query": pname}})
        elif task_type in ["rank", "compare"]:
            # PRIORITY: Check for review ranking first (most specific)
            if intent.get("ranking_by") == "review_score":
                category = intent.get("constraints", {}).get("category")
                if category:
                    plan.append(
                        {
                            "name": "get_best_reviewed_products_tool",
                            "args": {"limit": 10, "category": category},
                        }
                    )
                else:
                    plan.append(
                        {
                            "name": "get_best_reviewed_products_tool",
                            "args": {"limit": 10},
                        }
                    )
            elif task_type == "compare":
                # Multi-entity compare: split by any connector word
                pq = intent.get("product_query", "")
                split_part = None
                for sep in [" vs ", " và ", " and ", " v/s "]:
                    if sep in pq:
                        split_part = pq.split(sep, 1)
                        break
                if split_part and len(split_part) == 2:
                    plan.append(
                        {
                            "name": "search_products_v2",
                            "args": {"query": split_part[0].strip()},
                        }
                    )
                    plan.append(
                        {
                            "name": "search_products_v2",
                            "args": {"query": split_part[1].strip()},
                        }
                    )
            elif intent.get("product_query"):
                plan.append(
                    {
                        "name": "search_products_v2",
                        "args": {"query": intent.get("product_query")},
                    }
                )
                plan.append({"name": "__fetch_reviews_for_context__", "args": {}})
            else:
                plan.append({"name": "__fetch_reviews_for_context__", "args": {}})
        elif task_type == "list_categories":
            plan.append({"name": "get_categories", "args": {}})
        elif task_type == "list_products":
            plan.append({"name": "get_all_products", "args": {}})
        elif task_type == "search":
            # PRIORITY: Check for price constraints first
            constraints = intent.get("constraints", {})
            price_max = constraints.get("price_max")
            price_min = constraints.get("price_min")
            product_query = intent.get("product_query", "")

            if price_max is not None or price_min is not None:
                # FIX D: If user has BOTH a keyword and a price constraint,
                # run BOTH tools so synthesis can filter by keyword+price together.
                if product_query:
                    # Mark the intent so synthesis knows to filter by keyword too
                    intent["_price_filter_query"] = product_query
                    plan.append(
                        {"name": "search_products_v2", "args": {"query": product_query}}
                    )

                # Always run price range tool when price constraint exists
                args: dict = {"limit": 20}
                if price_max is not None:
                    args["max_price"] = price_max
                if price_min is not None:
                    args["min_price"] = price_min
                plan.append({"name": "get_products_by_price_range", "args": args})
            else:
                # Regular search — no price constraint
                q = intent.get("product_query", "")
                plan.append({"name": "search_products_v2", "args": {"query": q}})
        elif task_type == "convert_currency":
            # Currency conversion for product prices
            # Strategy: If product_name is specified, look up the product to get its USD price,
            # then convert that price to the target currency.
            # If no product specified, convert a default amount (useful for generic "how much is 100 USD in EUR")

            pname = intent.get("product_name")
            from_curr = intent.get("from_currency") or "USD"
            to_curr = intent.get("to_currency") or "VND"

            if pname:
                # Product-specific conversion: get product price first
                plan.append({"name": "search_products_v2", "args": {"query": pname}})
                # Note: We'll need to extract price from search result in executor
                # For now, mark intent so synthesis knows this is product price conversion
                intent["_convert_product_price"] = True

            # Always add conversion step (executor will use actual price if available)
            plan.append(
                {
                    "name": "convert_currency_tool",
                    "args": {
                        "from_currency": from_curr,
                        "to_currency": to_curr,
                        "amount_units": intent.get(
                            "quantity", 1
                        ),  # Default to 1 if no product context
                    },
                }
            )
        elif task_type == "get_shipping":
            address = intent.get("shipping_address") or intent.get("product_query", "")
            plan.append(
                {"name": "get_shipping_quote_tool", "args": {"address": address}}
            )
        elif task_type == "get_recommendations":
            if intent.get("target_entity") == "cart":
                plan.append({"name": "get_cart_tool", "args": {"user_id": user_id}})
                plan.append(
                    {
                        "name": "get_recommendations_tool",
                        "args": {"product_id": "$PREV_CART"},
                    }
                )
            else:
                constraints = intent.get("constraints", {})
                price_max = constraints.get("price_max")
                price_min = constraints.get("price_min")
                pname = intent.get("product_name")
                pid = intent.get("product_id")
                product_query = intent.get("product_query", "")

                # Generic category terms that shouldn't be resolved with get_product_id
                _generic_pnames = {
                    "astronomy accessory",
                    "accessory",
                    "accessories",
                    "telescope",
                    "telescopes",
                    "product",
                    "products",
                }

                if (
                    price_max is not None
                    or price_min is not None
                    or (pname and pname.lower() in _generic_pnames)
                ):
                    # Reclassify as search with optional price filter
                    q_term = product_query or pname or "accessory"
                    intent["_price_filter_query"] = q_term
                    plan.append(
                        {"name": "search_products_v2", "args": {"query": q_term}}
                    )
                    args_pf: dict = {"limit": 20}
                    if price_max is not None:
                        args_pf["max_price"] = price_max
                    if price_min is not None:
                        args_pf["min_price"] = price_min
                    if price_max is not None or price_min is not None:
                        plan.append(
                            {"name": "get_products_by_price_range", "args": args_pf}
                        )
                elif pid:
                    plan.append(
                        {
                            "name": "get_recommendations_tool",
                            "args": {"product_id": pid},
                        }
                    )
                elif pname:
                    plan.append(
                        {"name": "get_product_id", "args": {"product_name": pname}}
                    )
                    plan.append(
                        {
                            "name": "get_recommendations_tool",
                            "args": {"product_id": "$PREV"},
                        }
                    )
                else:
                    plan.append(
                        {
                            "name": "get_recommendations_tool",
                            "args": {"product_id": "$CTX"},
                        }
                    )

        if intent.get("needs_reviews"):
            plan.append({"name": "__fetch_reviews_for_context__", "args": {}})

        return plan

    # LAYER 3 & 4: Executor + Evidence Aggregator
    async def _execute_and_aggregate(
        self, plan: List[dict], user_id: str, session: dict
    ) -> dict:
        import asyncio

        evidence = {}
        prev_result = None
        extracted_price = None  # Track product price for currency conversion

        for step in plan:
            tc_name = step["name"]
            tc_args = dict(step.get("args", {}))

            # Resolve dependencies
            if tc_args.get("product_id") == "$PREV":
                if (
                    isinstance(prev_result, dict)
                    and prev_result.get("status") == "not_found"
                ):
                    pname = prev_result.get("product_name", "")
                    return {
                        "status": "error",
                        "error": f"Xin lỗi, không tìm thấy sản phẩm '{pname}' trong hệ thống. Vui lòng kiểm tra lại tên sản phẩm hoặc thử tìm kiếm bằng từ khóa khác.",
                    }
                if isinstance(prev_result, dict) and prev_result.get("product_id"):
                    tc_args["product_id"] = prev_result["product_id"]
                elif session.get("context", {}).get("last_product_id"):
                    tc_args["product_id"] = session["context"]["last_product_id"]
                else:
                    return {
                        "status": "error",
                        "error": "Xin lỗi, không thể xác định sản phẩm bạn đang muốn thực hiện thao tác. Vui lòng tìm kiếm sản phẩm trước.",
                    }

            elif tc_args.get("product_id") == "$PREV_CART":
                if isinstance(prev_result, dict) and prev_result.get("items"):
                    tc_args["product_id"] = prev_result["items"][0]["product_id"]
                else:
                    return {
                        "status": "error",
                        "error": "Your cart is empty. Cannot find related products.",
                    }

            elif tc_args.get("product_id") == "$CTX":
                if session.get("context", {}).get("last_product_id"):
                    tc_args["product_id"] = session["context"]["last_product_id"]
                else:
                    # No context product to bind $CTX to → skip this step instead of
                    # killing the whole turn with a hard error. Synthesis then runs
                    # with whatever evidence exists (possibly empty) and politely
                    # explains scope / asks the user to search first. Prevents the
                    # dead-end error reply on multilingual recommend flows (TC_MUL_001).
                    continue

            if tc_name == "__fetch_reviews_for_context__":
                search_ids = session.get("context", {}).get("last_search_ids", [])
                if not search_ids and session.get("context", {}).get("last_product_id"):
                    search_ids = [session["context"]["last_product_id"]]

                rev_tool = TOOLS_MAP.get("get_product_reviews_tool")

                async def fetch_one(pid):
                    try:
                        r_str = await rev_tool.ainvoke({"product_id": pid})
                        return json.loads(r_str)
                    except Exception as e:
                        return {"product_id": pid, "status": "error", "error": str(e)}

                all_reviews = await asyncio.gather(
                    *[fetch_one(pid) for pid in search_ids[:5]]
                )

                evidence[tc_name] = {
                    "status": "success",
                    "products_context": session.get("context", {}).get(
                        "last_search_results", []
                    ),
                    "results": list(all_reviews),
                }
                continue

            validation = validate_tool_call(tc_name, tc_args, user_id)
            if not validation.is_valid:
                return {
                    "status": "error",
                    "error": f"Blocked: {validation.blocked_reason}",
                }

            tool_fn = TOOLS_MAP.get(tc_name)
            if not tool_fn:
                continue

            try:
                # ── Special handling for currency conversion: inject product price ──
                if tc_name == "convert_currency_tool" and extracted_price is not None:
                    # Override amount_units with actual product price
                    tc_args["amount_units"] = int(extracted_price)
                    logger.info(
                        f"[CURRENCY] Using extracted product price: ${extracted_price}"
                    )

                # ── Kiểm tra Cache Tool ──
                cached_str = self._cache.get(tc_name, tc_args)
                if cached_str is not None:
                    res_str = cached_str
                    logger.debug(f"Cache HIT for tool {tc_name}")
                else:
                    res_str = await tool_fn.ainvoke(tc_args)
                    self._cache.set(tc_name, tc_args, res_str)
                    logger.debug(f"Cache MISS for tool {tc_name}")

                try:
                    res_json = json.loads(res_str)
                except Exception:
                    res_json = {"raw": res_str}

                # Extract product price from search results for currency conversion
                if (
                    tc_name == "search_products_v2"
                    and res_json.get("status") == "success"
                ):
                    products = res_json.get("products", [])
                    if products and isinstance(products[0], dict):
                        price_str = products[0].get("price", "")
                        # Parse price like "$349.95" or "349.95"
                        try:
                            extracted_price = float(
                                price_str.replace("$", "").replace(",", "").strip()
                            )
                            logger.info(
                                f"[CURRENCY] Extracted price from search: ${extracted_price}"
                            )
                        except (ValueError, AttributeError):
                            logger.warning(
                                f"[CURRENCY] Could not parse price: {price_str}"
                            )

                if tc_name in evidence:
                    # Merge products array so evidence retains products from all search steps in this turn
                    existing = evidence[tc_name]
                    if isinstance(existing, dict) and isinstance(res_json, dict):
                        existing_prods = existing.get("products", [])
                        new_prods = res_json.get("products", [])
                        existing_ids = {
                            p.get("id")
                            for p in existing_prods
                            if isinstance(p, dict) and p.get("id")
                        }
                        combined = list(existing_prods)
                        for p in new_prods:
                            if isinstance(p, dict) and p.get("id") not in existing_ids:
                                combined.append(p)
                                existing_ids.add(p.get("id"))
                        existing["products"] = combined
                        existing["total"] = len(combined)
                else:
                    evidence[tc_name] = res_json

                # Update context
                ctx = session.setdefault("context", {})
                if tc_name == "get_product_id" and res_json.get("status") == "success":
                    ctx["last_product_id"] = res_json.get("product_id")
                    ctx["last_product_name"] = res_json.get("product_name")
                elif (
                    tc_name == "search_products_v2"
                    and res_json.get("status") == "success"
                ):
                    prods = res_json.get("products", [])
                    if prods:
                        ctx["last_product_id"] = prods[0]["id"]
                        ctx["last_product_name"] = prods[0]["name"]
                        ctx["last_search_ids"] = [p["id"] for p in prods]
                        ctx["last_search_results"] = prods
                        # FIX A: Accumulate top-1 from each search step into
                        # _multi_search_tops so "both"/"cả hai" in the NEXT
                        # turn can resolve to both compared products even after
                        # the second search overwrites last_search_results.
                        acc = ctx.setdefault("_multi_search_tops", [])
                        if not acc or acc[-1].get("id") != prods[0]["id"]:
                            acc.append(prods[0])
                        # Keep at most 5 entries so context doesn't bloat
                        if len(acc) > 5:
                            ctx["_multi_search_tops"] = acc[-5:]
                elif (
                    tc_name == "get_all_products"
                    and res_json.get("status") == "success"
                ):
                    prods = res_json.get("products", [])
                    if prods:
                        ctx["last_search_ids"] = [p["id"] for p in prods]
                        ctx["last_search_results"] = prods

                if res_json.get("status") == "pending":
                    # Get intent from session context (stored before execution)
                    intent = session.get("context", {}).get("_current_intent", {})
                    pname1 = intent.get("product_name")
                    pname2 = intent.get("product_name_2")
                    if pname1 and pname2 and "message" in res_json:
                        res_json["message"] = (
                            f"Tôi đã sẵn sàng thực hiện thêm **{pname1}** và **{pname2}** vào giỏ hàng.\n\n"
                            f"**Để xác nhận:** Gõ **'xác nhận'**, **'ok'**, hoặc **'đồng ý'**\n"
                            f"**Để hủy:** Gõ **'hủy'** hoặc **'không'**"
                        )
                    elif pname1 and "message" in res_json:
                        res_json["message"] = (
                            f"Tôi đã sẵn sàng thực hiện thêm **{pname1}** vào giỏ hàng.\n\n"
                            f"**Để xác nhận:** Gõ **'xác nhận'**, **'ok'**, hoặc **'đồng ý'**\n"
                            f"**Để hủy:** Gõ **'hủy'** hoặc **'không'**"
                        )
                    return res_json  # Return immediately for pending actions

            except Exception as e:
                evidence[tc_name] = {"status": "error", "error": str(e)}

        # Persist the updated context to SessionStore
        if "session_id" in session:
            self._sessions.save(session["session_id"], session)

        return {"status": "success", "evidence": evidence}

    def _clean_placeholders(self, reply: str) -> str:
        """FIX E: Remove unreplaced template tokens from reply to prevent them appearing in UI."""
        import re

        if not reply:
            return reply
        # Remove $CTX, $PREV, $PREV_CART literal placeholders not replaced by executor
        reply = re.sub(r"\$(?:CTX|PREV(?:_CART)?)\b", "", reply)
        # Remove bracketed placeholder strings like [List available...], [Tên sản phẩm...], [Giá...]
        reply = re.sub(
            r"\[(?:List|product|insert|Tên|Giá|Mô tả|Dữ liệu)[^\]]*\]",
            "",
            reply,
            flags=re.IGNORECASE,
        )
        # Clean up any double blank lines created by removal
        reply = re.sub(r"\n{3,}", "\n\n", reply)
        return reply.strip()

    async def _check_faithfulness(self, evidence: dict, reply: str) -> bool:
        if not self.llm or not evidence:
            return True
        # Skip guard for explicit refusal/error replies — they're intentional, not hallucination
        lower = reply.lower()
        if any(
            kw in lower for kw in ["sự cố kỹ thuật", "lỗi kỹ thuật", "technical error"]
        ):
            return True
        if len(reply) < 30:
            return True

        # FIX B: Check if evidence has actual product data.
        # If yes, a reply that says "no information" is itself the hallucination — skip price check.
        has_products = False
        for k, v in evidence.items():
            if k.startswith("__"):
                continue
            if isinstance(v, dict) and len(v.get("products", [])) > 0:
                has_products = True
                break
            if isinstance(v, dict) and v.get("total", 0) > 0:
                has_products = True
                break

        # If evidence HAS products but reply says "no information" — that's the real problem,
        # but the faithfulness guard would just swap with another "no information" reply,
        # making things worse. Trust the synthesis in this case and let prompt rules handle it.
        abstain_phrases = [
            "không có thông tin",
            "xin lỗi, tôi không",
            "không thể tìm",
            "không có trong",
            "no information",
            "don't have information",
            "cannot find",
            "do not have",
            "don't have",
            "not have a",
            "do not possess",
            "unfortunately, we do not",
            "not found in our catalog",
            "do not have a",
        ]
        if has_products and any(p in lower for p in abstain_phrases):
            # Evidence has data but reply is refusing — this is a synthesis failure,
            # NOT a hallucination. Don't override with another refusal.
            logger.warning(
                "[GUARDRAIL] Synthesis refusal detected despite having evidence data — skipping faithfulness override."
            )
            return True

        prompt = f"""
You are a strict faithfulness checker. Compare the REPLY with the EVIDENCE.

FAIL only if the REPLY contains SPECIFIC FACTS (numbers, names, specifications) that DIRECTLY CONTRADICT facts in the EVIDENCE.
For example: FAIL if reply says price=$57.00 but evidence says price=57.08.

PASS if:
- Reply correctly synthesizes evidence (even if not listing every product)
- Reply says "no products" when evidence.products is empty or has status=error
- Reply appropriately abstains about non-product questions (NASA, warranty, etc.)
- Reply lists a subset of evidence products (not a contradiction)

EVIDENCE (truncated):
{json.dumps(evidence, ensure_ascii=False)[:16000]}

REPLY:
{reply}

Respond with exactly one word: PASS or FAIL
"""
        try:
            response = await self._call_llm([HumanMessage(content=prompt)])
            text = self._extract_text(response).strip().upper()
            return "FAIL" not in text
        except Exception as e:
            logger.error(f"Faithfulness check failed: {e}")
            return True

    # LAYER 5 & 6: Answer Generator + Grounding
    async def _generate_grounded_answer(
        self, user_message: str, evidence: dict, intent: dict
    ) -> str:
        if not self.llm:
            return (
                f"Evidence retrieved: {json.dumps(evidence, ensure_ascii=False)[:500]}"
            )

        # Inject intent metadata into evidence so LLM has full context
        evidence["__intent_meta__"] = {
            "task_type": intent.get("task_type"),
            "target_entity": intent.get("target_entity"),
        }

        # FIX D: Inject price_filter_query so synthesis can filter by both keyword AND price
        if intent.get("_price_filter_query"):
            evidence["__intent_meta__"]["price_filter_query"] = intent[
                "_price_filter_query"
            ]

        # ── Attribute mismatch detection ──────────────────────────────────────
        # If the user searched with a specific attribute/subtype (product_query),
        # check whether any returned product's name actually contains that attribute.
        # If none match, inject a flag so the synthesis LLM can reliably report
        # "no matching products" rather than mislabeling mismatched results.
        # This is a pre-validation step so the LLM doesn't need to reason about it.
        product_query = intent.get("product_query", "")
        if product_query and intent.get("task_type") in ["list_products", "search"]:
            # Collect all product names returned in evidence
            all_product_names: list[str] = []
            for tool_result in evidence.values():
                if isinstance(tool_result, dict):
                    for p in tool_result.get("products", []):
                        if isinstance(p, dict) and p.get("name"):
                            all_product_names.append(p["name"].lower())

            if all_product_names:
                # Generic category/list words must NOT gate an attribute mismatch.
                # "all telescopes with prices" is a catalog browse, not a request for
                # a specific attribute/subtype — flagging it as unmatched forces the
                # synthesis LLM to abstain (root cause of TC_MUL_003 / TC_FAC_003).
                _generic_terms = {
                    "telescope",
                    "telescopes",
                    "binocular",
                    "binoculars",
                    "product",
                    "products",
                    "sản",
                    "phẩm",
                    "hàng",
                    "accessory",
                    "accessories",
                    "phụ",
                    "kiện",
                    "item",
                    "items",
                    "all",
                    "available",
                    "list",
                    "show",
                    "price",
                    "prices",
                    "the",
                    "with",
                    "kính",
                    "thiên",
                    "văn",
                    "viễn",
                    "vọng",
                    "ống",
                    "nhòm",
                    "dụng",
                    "cụ",
                    "thiết",
                    "bị",
                    "danh",
                    "sách",
                    "các",
                    "loại",
                    "tất",
                    "cả",
                    "giá",
                    "tìm",
                    "muốn",
                    "xem",
                    "tốt",
                    "nào",
                    "giúp",
                    "tôi",
                    "mình",
                    "giùm",
                    "cho",
                    "nhé",
                    "ơi",
                    "ơn",
                    "good",
                    "best",
                    "top",
                    "cheap",
                    "great",
                    "find",
                    "search",
                    "get",
                    "under",
                    "above",
                    "for",
                    "and",
                    "or",
                }
                query_terms = [
                    t.strip().lower()
                    for t in product_query.split()
                    if len(t.strip()) >= 2
                ]
                specific_terms = [t for t in query_terms if t not in _generic_terms]

                def _term_matches(term: str) -> bool:
                    # Match singular/plural in either direction (telescopes ⇄ Telescope).
                    term_sing = term.rstrip("s")
                    for name in all_product_names:
                        if term in name or (term_sing and term_sing in name):
                            return True
                        for w in name.split():
                            if w.rstrip("s") == term_sing:
                                return True
                    return False

                # Only flag a mismatch when the query carried a SPECIFIC attribute
                # (e.g. "reflector") and none of the returned products match it.
                if specific_terms:
                    any_match = any(_term_matches(t) for t in specific_terms)
                    if not any_match:
                        evidence["__intent_meta__"]["attribute_unmatched"] = True
                        evidence["__intent_meta__"][
                            "requested_attribute"
                        ] = product_query

        ev_str = json.dumps(evidence, ensure_ascii=False)
        prompt = EVIDENCE_SYNTHESIS_PROMPT.format(
            user_message=user_message, evidence=ev_str
        )

        try:
            response = await self._call_llm(
                [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
            )
            reply = self._extract_text(response)
            reply = self._clean_placeholders(reply)

            # ── CRITICAL: Price Validation Post-Processor ──
            # This validator ensures LLM doesn't round prices.
            # Extract all prices from evidence, check if any appear rounded in reply.
            reply = self._validate_and_fix_prices(reply, evidence)

            return reply
        except Exception as e:
            print(f"=== SYNTHESIS ERROR EXCEPTION ===: {e}")
            logger.error(f"Synthesis failed: {e}")
            return "Xin lỗi, tôi không có thông tin chi tiết về câu hỏi này dựa trên dữ liệu hiện tại."

    def _validate_and_fix_prices(self, reply: str, evidence: dict) -> str:
        """
        Validate that prices in reply match evidence exactly (no rounding).
        If LLM rounded a price, replace it with the exact evidence value.

        This is NOT a hardcoded rule, but a grounding enforcement layer that ensures
        LLM output faithfully reflects evidence data.
        """
        import re

        # Extract all product prices from evidence
        evidence_prices = {}  # product_name → exact_price
        for tool_result in evidence.values():
            if isinstance(tool_result, dict):
                for p in tool_result.get("products", []):
                    if isinstance(p, dict) and p.get("name") and p.get("price"):
                        name = p["name"]
                        price = float(p["price"])
                        evidence_prices[name.lower()] = price

        if not evidence_prices:
            return reply  # No prices to validate

        # Find all price mentions in reply: $X.XX, $X.X, $X
        price_pattern = re.compile(r"\$(\d+(?:\.\d{1,2})?)")
        replacements = []

        for match in price_pattern.finditer(reply):
            reply_price_str = match.group(1)
            reply_price = float(reply_price_str)

            # Find closest product name appearing before this price
            start_pos = max(0, match.start() - 200)
            context = reply[start_pos : match.start()].lower()

            best_pname = None
            best_pos = -1
            for product_name in evidence_prices:
                pos = context.rfind(product_name.lower())
                if pos > best_pos:
                    best_pos = pos
                    best_pname = product_name.lower()

            if best_pname:
                evidence_price = evidence_prices[best_pname]
                # If price in reply does not match exact evidence price for this product, correct it
                if abs(reply_price - evidence_price) > 0.001:
                    replacements.append((match.span(), evidence_price))
                    logger.warning(
                        f"[PRICE_VALIDATOR] Correcting price for product '{best_pname}': "
                        f"Reply was ${reply_price} | Correct evidence price: ${evidence_price}"
                    )

        # Apply replacements (in reverse order to preserve positions)
        for (start, end), correct_price in reversed(replacements):
            reply = reply[:start] + f"${correct_price:.2f}" + reply[end:]

        return reply

    @with_fallback
    async def chat(
        self, session_id: str, user_id: str, user_message: str, on_trace: Optional[Any] = None
    ) -> Dict[str, Any]:
        self._steps = []
        self._on_trace_callback = on_trace
        request_id = get_tracer().create_request_id()

        # ── MANDATE #23: GenAI Cache Check (trước rate limiter để tiết kiệm processing) ──
        self._emit_trace("cache_lookup", "Tra cứu Tier 1 Exact Match (Valkey) & Tier 2 Titan Semantic Vector Embeddings...")
        cache_hit_result = self._genai_cache.get(user_id, user_message)
        if cache_hit_result:
            logger.info(
                "[CHAT] GenAI Cache HIT | user=%s | session=%s", user_id, session_id
            )
            # Restore session state from cache
            session = self._sessions.get_or_create(session_id, user_id)
            self._sessions.append_message(session_id, "user", user_message)
            self._sessions.append_message(
                session_id, "assistant", cache_hit_result["reply"]
            )
            self._sessions.touch(session_id)

            # Return cached response with cache:hit flag
            return {
                "status": "ok",
                "reply": cache_hit_result["reply"],
                "session_id": session_id,
                "request_id": request_id,
                "token": None,
                "steps": cache_hit_result.get("steps", []),
                "intent": cache_hit_result.get("intent"),
                "evidence": cache_hit_result.get("evidence"),
                "cache": "hit",  # ← MANDATE #23: Cache flag for BTC validation
            }

        s1, a1 = self._time("RateLimiter")
        rate_res = rate_limiter.check_rate_limit(user_id)
        if not rate_res.is_allowed:
            self._end(s1, a1, "BLOCK", rate_res.blocked_reason)
            return {
                "status": "error",
                "reply": rate_res.blocked_reason,
                "session_id": session_id,
                "request_id": request_id,
                "steps": list(self._steps),
                "cache": "miss",
            }
        self._end(s1, a1, "PASS", "Rate OK")

        # LAYER 0.5: Check for pending confirmation and detect confirmation keywords
        session = self._sessions.get_or_create(session_id, user_id)
        pending = session.get("pending_confirmation", {})

        if pending.get("token"):
            # User has a pending confirmation - check if this message is a confirmation response
            msg_lower = user_message.lower().strip()

            # Confirmation keywords/phrases in multiple languages
            # Mix of single words and multi-word phrases
            confirm_phrases = [
                "yes",
                "ok",
                "okay",
                "confirm",
                "agreed",
                "accept",
                "có",
                "đúng",
                "oke",
                "oki",
                "xác nhận",
                "xac nhan",  # Vietnamese multi-word
                "đồng ý",
                "dong y",  # Vietnamese multi-word
            ]
            cancel_phrases = [
                "no",
                "cancel",
                "nope",
                "không",
                "khong",
                "hủy",
                "huy",
                "thôi",
                "bỏ",
            ]

            # Check for phrase matches (handles both single-word and multi-word)
            def matches_phrase(text: str, phrases: list) -> bool:
                for phrase in phrases:
                    if phrase in text:
                        return True
                return False

            if matches_phrase(msg_lower, confirm_phrases):
                # User is confirming - execute the pending action
                logger.info(
                    f"[CHAT] Detected confirmation keyword in: '{user_message}'"
                )
                return await self.confirm(
                    session_id=session_id, token=pending["token"], confirmed=True
                )

            elif matches_phrase(msg_lower, cancel_phrases):
                # User is canceling
                logger.info(
                    f"[CHAT] Detected cancellation keyword in: '{user_message}'"
                )
                return await self.confirm(
                    session_id=session_id, token=pending["token"], confirmed=False
                )

            # If user says something else while pending, provide clear guidance
            elif len(msg_lower) < 50:
                # Short message that doesn't look like a new query - probably confused about how to confirm
                return {
                    "status": "pending",
                    "reply": (
                        "💡 Bạn đang có một hành động chờ xác nhận (thêm sản phẩm vào giỏ hàng).\n\n"
                        "**Cách xác nhận:**\n"
                        "• Gõ: **xác nhận** / **ok** / **đồng ý** / **yes**\n"
                        "• Hoặc gõ: **hủy** / **không** nếu muốn hủy bỏ\n\n"
                        "Bạn cũng có thể bắt đầu tìm kiếm sản phẩm khác - hành động chờ xác nhận sẽ được giữ lại."
                    ),
                    "token": pending["token"],
                    "session_id": session_id,
                    "request_id": request_id,
                    "steps": [],
                }

        s2, a2 = self._time("InputFilter")
        if not check_input_bedrock(user_message).is_safe:
            detail = "Message blocked by safety filters."
            self._end(s2, a2, "BLOCK", detail)
            return {
                "status": "error",
                "reply": detail,
                "session_id": session_id,
                "request_id": request_id,
                "steps": list(self._steps),
                "intent": {},
                "evidence": {},
            }
        self._end(s2, a2, "PASS", "Safety OK")

        # Sanitize PII from user_message before any LLM call.
        # This ensures the LLM never "sees" raw PII (SSN, credit card, email, phone)
        # and therefore cannot accidentally summarize, mention, or echo it in outputs.
        user_message = sanitize_pii_from_input(user_message)

        session = self._sessions.get_or_create(session_id, user_id)
        self._sessions.append_message(session_id, "user", user_message)

        # L1: Parse Intent
        self._emit_trace("intent_parser", "Phân tích ý định câu hỏi (Intent Parsing)...")
        trace_llm_ctx.set({"layer": "intent_parser", "request_id": request_id, "session_id": session_id, "user_id": user_id})
        s3, a3 = self._time("IntentParser")
        raw_intent = await self._parse_intent_with_llm(user_message, session)
        intent = self._resolve_context_references(raw_intent, session)
        self._end(
            s3,
            a3,
            "OK",
            f"Parsed: {intent.get('task_type')} on {intent.get('target_entity')}",
        )

        if intent.get("needs_clarification"):
            reply = intent.get("clarification_question", "Could you please clarify?")
            self._sessions.append_message(session_id, "assistant", reply)
            return {
                "status": "ok",
                "reply": reply,
                "session_id": session_id,
                "request_id": request_id,
                "steps": list(self._steps),
                "intent": intent,
                "evidence": {},
                "cache": "miss",
            }

        # Short-circuit: task types that never require tool execution.
        # Route them directly to answer generation with empty evidence so the LLM
        # produces a principled refusal/greeting grounded in the intent meta,
        # not an implementation detail (e.g. "cart is empty").
        _NO_TOOL_TASKS = {"greeting", "unknown", "unsupported_cart_action", "clarify"}
        if intent.get("task_type") in _NO_TOOL_TASKS:
            self._emit_trace("synthesis", "Sinh câu trả lời trực tiếp...")
            trace_llm_ctx.set({"layer": "synthesis", "request_id": request_id, "session_id": session_id, "user_id": user_id})
            s_skip, a_skip = self._time("AnswerGenerator")
            reply = await self._generate_grounded_answer(user_message, {}, intent)
            output_filtered = filter_output(reply)
            reply = output_filtered.filtered_response
            self._end(
                s_skip,
                a_skip,
                "OK",
                f"Direct answer for task_type={intent.get('task_type')}",
            )
            self._sessions.append_message(session_id, "assistant", reply)
            self._sessions.touch(session_id)
            return {
                "status": "ok",
                "reply": reply,
                "session_id": session_id,
                "request_id": request_id,
                "steps": list(self._steps),
                "intent": intent,
                "evidence": {},
                "cache": "miss",
            }

        # L2: Planner
        self._emit_trace("planning", "Lập kế hoạch thực thi (Heuristic / LLM Plan)...")
        trace_llm_ctx.set({"layer": "planner", "request_id": request_id, "session_id": session_id, "user_id": user_id})
        s4, a4 = self._time("Planner")
        plan = await self._build_plan_with_llm(intent, user_id, session)
        self._end(s4, a4, "OK", f"Plan steps: {len(plan)}")

        # Store intent in session so _execute_and_aggregate can access it for pending messages
        session.setdefault("context", {})["_current_intent"] = intent

        # L3 & L4: Execute and Aggregate
        self._emit_trace("tool_call", f"Thực thi {len(plan)} bước dịch vụ (Tool Calls)...")
        s5, a5 = self._time("Executor")
        exec_result = await self._execute_and_aggregate(plan, user_id, session)
        self._end(s5, a5, "OK", f"Execution status: {exec_result.get('status')}")

        if exec_result.get("status") == "pending":
            reply = exec_result.get("message", "Confirmation needed.")
            self._sessions.set_pending(
                session_id,
                exec_result["token"],
                "AddItem",
                exec_result.get("action_data"),
            )
            self._sessions.append_message(session_id, "assistant", reply)
            return {
                "status": "pending",
                "reply": reply,
                "token": exec_result["token"],
                "session_id": session_id,
                "request_id": request_id,
                "steps": list(self._steps),
                "intent": intent,
                "evidence": exec_result.get("evidence", {}),
                "cache": "miss",
            }

        if exec_result.get("status") == "error":
            reply = exec_result.get("error", "Error executing plan.")
            self._sessions.append_message(session_id, "assistant", reply)
            return {
                "status": "error",
                "reply": reply,
                "session_id": session_id,
                "request_id": request_id,
                "steps": list(self._steps),
                "intent": intent,
                "evidence": exec_result.get("evidence", {}),
                "cache": "miss",
            }

        # L5 & L6: Answer Gen + Guarding
        self._emit_trace("synthesis", "Tổng hợp câu trả lời & Kiểm tra Guardrails...")
        trace_llm_ctx.set({"layer": "synthesis", "request_id": request_id, "session_id": session_id, "user_id": user_id})
        s6, a6 = self._time("AnswerGenerator")
        reply = await self._generate_grounded_answer(
            user_message, exec_result.get("evidence", {}), intent
        )
        logger.info(f"=== DEBUG RAW REPLY ===\n{reply}\n=======================")

        # Faithfulness Guard (skip for direct catalog/cart actions like search, lookup, list_products, list_categories, add_to_cart, view_cart)
        if intent.get("task_type") not in [
            "greeting",
            "unsupported_cart_action",
            "unknown",
            "list_products",
            "list_categories",
            "search",
            "lookup",
            "add_to_cart",
            "view_cart",
        ]:
            trace_llm_ctx.set({"layer": "faithfulness_guard", "request_id": request_id, "session_id": session_id, "user_id": user_id})
            is_faithful = await self._check_faithfulness(
                exec_result.get("evidence", {}), reply
            )
            logger.info(f"[DEBUG_FAITHFULNESS] Is faithful: {is_faithful}")
            if not is_faithful:
                logger.warning("[GUARDRAIL] Hallucination detected. Overriding reply.")
                reply = "Xin lỗi, tôi không có thông tin chi tiết về câu hỏi này dựa trên dữ liệu hiện tại."

        output_filtered = filter_output(reply)
        reply = output_filtered.filtered_response
        self._end(s6, a6, "OK", "Answer generated and filtered")

        self._sessions.append_message(session_id, "assistant", reply)
        self._sessions.touch(session_id)

        # ── MANDATE #23: Cache GenAI Response (Post-Guardrail) ──
        response_data = {
            "reply": reply,
            "steps": list(self._steps),
            "intent": intent,
            "evidence": exec_result.get("evidence", {}),
        }

        # Extract entities for cache invalidation
        entities = []
        if intent.get("product_id"):
            entities.append({"type": "product", "id": intent["product_id"]})

        evidence = exec_result.get("evidence", {})
        if isinstance(evidence, dict):
            for k, v in evidence.items():
                if isinstance(v, dict):
                    if v.get("product_id"):
                        entities.append({"type": "product", "id": v["product_id"]})
                    for item in v.get("products", []):
                        if isinstance(item, dict) and item.get("id"):
                            entities.append({"type": "product", "id": item["id"]})
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict) and item.get("id"):
                            entities.append({"type": "product", "id": item["id"]})

        import re
        prod_matches = re.findall(r'\b[A-Z0-9]{8,12}\b', user_message)
        for pm in prod_matches:
            if pm not in [user_id, session_id]:
                entities.append({"type": "product", "id": pm})

        self._genai_cache.set(user_id, user_message, response_data, entities)

        # ── MANDATE #23: Extract & Store Long-term Memory ──
        self._extract_and_store_longterm_memory(
            user_id, user_message, intent, exec_result
        )

        return {
            "status": "ok",
            "reply": reply,
            "session_id": session_id,
            "request_id": request_id,
            "steps": list(self._steps),
            "intent": intent,
            "evidence": exec_result.get("evidence", {}),
            "cache": "miss",  # ← MANDATE #23: Cache flag (this is a fresh response)
        }

    async def confirm(
        self, session_id: str, token: str, confirmed: bool = True
    ) -> Dict[str, Any]:
        is_valid, action_data = verify_confirmation_token(token)
        if not is_valid:
            return {"status": "error", "reply": "Token không hợp lệ hoặc đã hết hạn."}

        self._sessions.clear_pending(session_id)

        if not confirmed:
            self._sessions.append_message(session_id, "user", "Hủy xác nhận")
            self._sessions.append_message(
                session_id, "assistant", "❌ Đã hủy thao tác thêm vào giỏ hàng."
            )
            return {
                "status": "cancelled",
                "reply": "❌ Đã hủy thao tác thêm vào giỏ hàng.",
            }

        import grpc
        from src.protos import demo_pb2_grpc, demo_pb2
        from src.tools.service_config import CART_ADDR

        channel = grpc.insecure_channel(CART_ADDR)
        try:
            stub = demo_pb2_grpc.CartServiceStub(channel)
            stub.AddItem(
                demo_pb2.AddItemRequest(
                    user_id=action_data["user_id"],
                    item=demo_pb2.CartItem(
                        product_id=action_data["params"]["product_id"],
                        quantity=action_data["params"]["quantity"],
                    ),
                ),
                timeout=3.0,
            )
            self._sessions.append_message(session_id, "user", "Xác nhận hành động")
            self._sessions.append_message(
                session_id, "assistant", "✅ Đã thêm vào giỏ hàng thành công!"
            )
            return {"status": "ok", "reply": "✅ Đã thêm vào giỏ hàng thành công!"}
        except grpc.RpcError as e:
            return {"status": "error", "reply": f"Lỗi gRPC: {e.details()}"}
        finally:
            channel.close()

    # ── MANDATE #23: Long-term Memory Extraction ──
    def _extract_and_store_longterm_memory(
        self, user_id: str, user_message: str, intent: dict, exec_result: dict
    ) -> None:
        """
        Trích xuất và lưu thông tin vào Long-term Memory.
        Được gọi sau mỗi lần chat thành công.
        """
        try:
            task_type = intent.get("task_type")

            # Update interaction summary
            topics = []
            if task_type == "search":
                query = intent.get("product_query", "")
                if query:
                    topics.append(query[:50])  # First 50 chars as topic
            elif task_type in ["lookup", "get_reviews"]:
                pname = intent.get("product_name", "")
                if pname:
                    topics.append(pname)

            self._longterm_memory.update_interaction_summary(user_id, topics)

            # Extract preferences from constraints
            constraints = intent.get("constraints", {})
            if constraints:
                if constraints.get("price_max"):
                    self._longterm_memory.add_preference(
                        user_id,
                        "budget",
                        f"under {constraints['price_max']} USD",
                        confidence=0.7,
                    )
                if constraints.get("category"):
                    self._longterm_memory.add_preference(
                        user_id, "category", constraints["category"], confidence=0.8
                    )

            # Extract purchase info from add_to_cart
            if task_type == "add_to_cart" and exec_result.get("status") != "pending":
                product_id = intent.get("product_id")
                product_name = intent.get("product_name", "")
                if product_id and product_name:
                    self._longterm_memory.add_purchase(
                        user_id, product_id, product_name
                    )

            # Extract product interest from searches
            if task_type == "search" and exec_result.get("evidence"):
                evidence = exec_result.get("evidence", {})
                products = evidence.get("products", [])
                if products and len(products) > 0:
                    # User is interested in this category/type
                    first_product = products[0]
                    if isinstance(first_product, dict):
                        categories = first_product.get("categories", [])
                        if categories:
                            self._longterm_memory.add_preference(
                                user_id, "category", categories[0], confidence=0.6
                            )

        except Exception as e:
            logger.warning("[LONGTERM] Failed to extract memory: %s", e)

    @property
    def sessions(self) -> "SessionStore":
        return self._sessions

    @property
    def cache_store(self) -> "CacheStore":
        return self._cache

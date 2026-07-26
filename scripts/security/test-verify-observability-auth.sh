#!/usr/bin/env bash
set -euo pipefail

echo "Running SEC - Observability Redirect Parser Unit Tests"

eval "$(sed -n '/trusted_access_redirect() {/,/^}/p' scripts/security/verify-observability-auth.sh)"

declare -i ERRORS=0

test_trusted() {
  local url="$1"
  if trusted_access_redirect "$url"; then
    echo "PASS (trusted): $url"
  else
    echo "FAIL (trusted): $url was rejected"
    ERRORS+=1
  fi
}

test_untrusted() {
  local url="$1"
  if trusted_access_redirect "$url"; then
    echo "FAIL (untrusted): $url was accepted"
    ERRORS+=1
  else
    echo "PASS (untrusted): $url was rejected"
  fi
}

test_trusted "https://team.cloudflareaccess.com/cdn-cgi/access/login"
test_trusted "https://sub.team.cloudflareaccess.com/path"

test_untrusted "https://evil.example/?next=.cloudflareaccess.com"
test_untrusted "https://cloudflareaccess.com.evil.example/"
test_untrusted "http://team.cloudflareaccess.com/"
test_untrusted ""

echo "Running Mock Tests for RBAC and Pod Queries"
test_rbac() {
  local mock_stdout="$1"
  local mock_exit="$2"
  local expected="$3"
  
  local result
  if [ $mock_exit -eq 0 ] && [ "$mock_stdout" = "yes" ]; then
      result="yes"
  elif [ $mock_exit -eq 1 ] && [[ "$mock_stdout" == "no"* ]]; then
      result="no"
  else
      result="QUERY_ERROR"
  fi
  
  if [ "$result" = "$expected" ]; then
      echo "PASS: RBAC mock (stdout: '$mock_stdout', rc: $mock_exit) -> $result"
  else
      echo "FAIL: RBAC mock (stdout: '$mock_stdout', rc: $mock_exit) -> expected $expected but got $result"
      ERRORS+=1
  fi
}

test_rbac "yes" 0 "yes"
test_rbac "no - reason" 1 "no"
test_rbac "no" 1 "no"
test_rbac "error connecting" 1 "QUERY_ERROR"
test_rbac "yes" 1 "QUERY_ERROR"
test_rbac "no" 0 "QUERY_ERROR"
test_rbac "" 0 "QUERY_ERROR"

test_pod_query() {
  local mock_stdout="$1"
  local mock_exit="$2"
  local expected="$3"
  
  local result
  if [ $mock_exit -ne 0 ]; then
      result="QUERY_ERROR"
  else
      local flagd=$(echo "$mock_stdout" | grep -E 'flagd-ui' || true)
      if [ -n "$flagd" ]; then
          result="FAIL"
      else
          result="PASS"
      fi
  fi
  
  if [ "$result" = "$expected" ]; then
      echo "PASS: Pod query mock (rc: $mock_exit, match: $(if [[ "$mock_stdout" == *"flagd"* ]]; then echo true; else echo false; fi)) -> $result"
  else
      echo "FAIL: Pod query mock (rc: $mock_exit, match: ...) -> expected $expected but got $result"
      ERRORS+=1
  fi
}

test_pod_query "some-other-pod" 0 "PASS"
test_pod_query "flagd-ui-container" 0 "FAIL"
test_pod_query "error connecting" 1 "QUERY_ERROR"

if [ $ERRORS -gt 0 ]; then
  echo "Unit tests failed with $ERRORS errors."
  exit 1
fi

echo "All redirect and mock unit tests passed."
exit 0

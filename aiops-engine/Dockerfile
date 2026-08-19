FROM --platform=$BUILDPLATFORM golang:1.26.5@sha256:3aff6657219a4d9c14e27fb1d8976c49c29fddb70ba835014f477e1c70636647 AS kubectl-builder

ARG TARGETOS TARGETARCH

WORKDIR /src

# Keep the Kubernetes 1.36 command surface while overriding vulnerable transitive
# Go modules until an upstream stable kubectl release contains their fixes.
COPY kubectl-builder/go.mod kubectl-builder/go.sum ./
RUN go mod download
COPY kubectl-builder/main.go ./
RUN CGO_ENABLED=0 GOOS="$TARGETOS" GOARCH="$TARGETARCH" \
    go build -mod=readonly -trimpath \
    -ldflags="-s -w \
      -X k8s.io/component-base/version.gitMajor=1 \
      -X k8s.io/component-base/version.gitMinor=36 \
      -X k8s.io/component-base/version.gitVersion=v1.36.3-aiops.1 \
      -X k8s.io/component-base/version.gitCommit=0f29094e5b73085e3802ecc1298ecae13866bfe6 \
      -X k8s.io/component-base/version.gitTreeState=clean \
      -X k8s.io/component-base/version.buildDate=2026-07-28T00:00:00Z" \
    -o /out/kubectl .

FROM python:3.10.20-alpine3.23@sha256:81c5715bb79d8edd45a82de842a29c7d6ef2aff4b7fa88e712f93a93806337df AS python-builder

WORKDIR /build

RUN apk add --no-cache build-base

COPY requirements.txt .
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt \
    && /venv/bin/pip uninstall -y pip setuptools wheel

FROM python:3.10.20-alpine3.23@sha256:81c5715bb79d8edd45a82de842a29c7d6ef2aff4b7fa88e712f93a93806337df

WORKDIR /app

# Runtime libraries required by the compiled scientific Python extensions.
RUN apk add --no-cache libgomp libstdc++
RUN python -m pip uninstall -y pip setuptools wheel

COPY --chmod=0755 --from=kubectl-builder /out/kubectl /usr/local/bin/kubectl
COPY --from=python-builder /venv /venv

# Copy the rest of the application code
COPY . .

# Grant read/write permissions to non-root user 10001 for S3 model downloads
RUN chown -R 10001:10001 /app

# Expose port 8000
EXPOSE 8000

# Set environment variable defaults
ENV PATH="/venv/bin:$PATH"
ENV AIOPS_SIMULATION_MODE=false
ENV PORT=8000

# Start Uvicorn server
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

CLUSTER_NAME := sus
REGISTRY := localhost:5050
CLUSTER_REGISTRY := sus-registry:5050
LANDING_IMAGE := $(REGISTRY)/sus-landing
BUILD_POD_IMAGE := $(REGISTRY)/sus-build
TAG := dev
GIT_REPO_URL ?= https://github.com/dev-dull/sus-starter-pack.git

.PHONY: help cluster-up cluster-down build push build-pod push-pod deploy upgrade dev teardown status logs

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Cluster lifecycle ---

cluster-up: ## Create k3d cluster with local registry
	k3d cluster create --config k3d.yaml
	@echo "Waiting for cluster to be ready..."
	kubectl wait --for=condition=Ready nodes --all --timeout=60s
	@echo "Cluster '$(CLUSTER_NAME)' is ready."

cluster-down: ## Delete k3d cluster
	k3d cluster delete $(CLUSTER_NAME)

# --- Build and push ---

build: ## Build all container images (landing + build pod)
	docker build -t $(LANDING_IMAGE):$(TAG) -f ./landing/Dockerfile .
	docker build -t $(BUILD_POD_IMAGE):$(TAG) -f ./build-pod/Dockerfile .

push: ## Push all images to the local registry
	docker push $(LANDING_IMAGE):$(TAG)
	docker push $(BUILD_POD_IMAGE):$(TAG)

build-pod: ## Build the build pod container image
	docker build -t $(BUILD_POD_IMAGE):$(TAG) -f ./build-pod/Dockerfile .

push-pod: ## Push the build pod image to the local registry
	docker push $(BUILD_POD_IMAGE):$(TAG)

# --- Deploy ---

deploy: ## Install the Helm chart into the cluster
	helm install sus ./charts/sus \
		--set landing.image.repository=$(CLUSTER_REGISTRY)/sus-landing \
		--set landing.image.tag=$(TAG) \
		--set gitRepo.url=$(GIT_REPO_URL)

upgrade: ## Upgrade the Helm release with latest values
	helm upgrade sus ./charts/sus \
		--set landing.image.repository=$(CLUSTER_REGISTRY)/sus-landing \
		--set landing.image.tag=$(TAG) \
		--set gitRepo.url=$(GIT_REPO_URL)

# --- Compound targets ---

dev: cluster-up build push deploy ## Full dev setup: cluster + build + deploy
	@echo ""
	@echo "SUS is running. Access the landing page:"
	@echo "  kubectl port-forward -n sus svc/sus-landing 8080:80"
	@echo ""

teardown: cluster-down ## Tear down everything

# --- Helpers ---

status: ## Show cluster and pod status
	@echo "=== Nodes ==="
	@kubectl get nodes
	@echo ""
	@echo "=== Pods (sus) ==="
	@kubectl get pods -n sus
	@echo ""
	@echo "=== Pods (sus-workloads) ==="
	@kubectl get pods -n sus-workloads
	@echo ""
	@echo "=== Services (sus) ==="
	@kubectl get svc -n sus

logs: ## Tail landing page pod logs
	kubectl logs -n sus -l app.kubernetes.io/component=landing -f

redeploy: build push upgrade ## Rebuild image and upgrade the deployment
	kubectl rollout restart deployment -n sus -l app.kubernetes.io/component=landing

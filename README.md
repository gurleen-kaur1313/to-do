# To-Do App on Docker, Minikube and EKS

CS-GY 9223 Cloud Computing, Fall 2026, Assignment 2. A Flask + MongoDB to-do app, containerized and deployed to Kubernetes.

Replace `YOUR_DOCKERHUB_USERNAME` in `docker-compose.yml` and the `k8s/*.yaml` files with your Docker Hub username before starting.

```
app/                         Flask app + Dockerfile
  app.py                     routes, /health (liveness), /ready (readiness), /fail (break liveness)
  templates/index.html       UI; shows app version and the pod that served the request
docker-compose.yml           Flask + MongoDB with a named volume
k8s/
  mongo-pvc.yaml             persistent volume claim for MongoDB data
  mongo-deployment.yaml      MongoDB pod
  mongo-service.yaml         internal ClusterIP service (mongo:27017)
  flask-deployment.yaml      3 replicas, RollingUpdate strategy, liveness + readiness probes
  flask-service.yaml         LoadBalancer service (port 80 -> 5000)
  replication-controller.yaml  alternative for Part 5 (use instead of flask-deployment.yaml)
eks/cluster.yaml             eksctl cluster definition
eks/storageclass.yaml        default gp3 StorageClass for EKS (needed by mongo-pvc)
monitoring/
  values.yaml                kube-prometheus-stack Helm values (Alertmanager -> Slack)
  alert-rules.yaml           PrometheusRule alerts for the app
```

## Endpoints

| Path | Purpose |
|---|---|
| `/` | To-do list UI |
| `/health` | Liveness probe. Returns 500 after `/fail` is called |
| `/ready` | Readiness probe. Returns 503 if MongoDB is unreachable |
| `/fail` | Makes this pod's liveness probe fail so Kubernetes restarts it |

## Part 2: Docker

```bash
# Run locally with Docker Compose
docker compose up --build -d
open http://localhost:8080
docker compose ps
docker compose down          # data persists in the mongo-data volume
docker compose down -v       # also deletes the data

# Build and push to Docker Hub
docker login
docker build -t YOUR_DOCKERHUB_USERNAME/todo-flask:v1 ./app
docker push YOUR_DOCKERHUB_USERNAME/todo-flask:v1
```

On an Apple Silicon Mac, build for both architectures so the image also runs on EKS x86 nodes:

```bash
docker buildx build --platform linux/amd64,linux/arm64 --build-arg APP_VERSION=v1 \
  -t YOUR_DOCKERHUB_USERNAME/todo-flask:v1 --push ./app
```

## Part 3: Minikube

```bash
brew install minikube
minikube start

kubectl apply -f k8s/
# The replication controller is the Part 5 alternative and duplicates the deployment's pods.
kubectl delete -f k8s/replication-controller.yaml --ignore-not-found

kubectl get pods,svc,pvc
minikube service flask-service --url     # open the printed URL
```

## Part 4: AWS EKS

```bash
brew install eksctl awscli
aws configure

eksctl create cluster -f eks/cluster.yaml           # takes about 15 minutes
aws eks update-kubeconfig --region us-east-1 --name todo-cluster
kubectl config current-context

# EKS has no default StorageClass, so mongo-pvc would stay Pending without this
kubectl apply -f eks/storageclass.yaml

kubectl apply -f k8s/mongo-pvc.yaml -f k8s/mongo-deployment.yaml -f k8s/mongo-service.yaml \
              -f k8s/flask-deployment.yaml -f k8s/flask-service.yaml
kubectl get pods,svc
kubectl get svc flask-service -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
# Open http://<that hostname> (the DNS name can take 1-2 minutes to resolve)
```

Delete the cluster when you are done so you are not billed:

```bash
eksctl delete cluster -f eks/cluster.yaml
```

To switch between clusters: `kubectl config get-contexts`, then `kubectl config use-context minikube`.

## Part 5: Deployments and ReplicaSets

```bash
kubectl apply -f k8s/flask-deployment.yaml
kubectl get deployment flask-app
kubectl get rs

# Delete a pod and watch the ReplicaSet replace it
kubectl get pods -l app=flask-app
kubectl delete pod <flask-app-pod-name>
kubectl get pods -l app=flask-app -w

# Scale
kubectl scale deployment flask-app --replicas=5
kubectl get pods -l app=flask-app
# or edit spec.replicas in k8s/flask-deployment.yaml and run kubectl apply again
```

### Alternative: Replication Controller

```bash
kubectl delete -f k8s/flask-deployment.yaml
kubectl apply -f k8s/replication-controller.yaml
kubectl get rc
kubectl delete pod <flask-rc-pod-name>
kubectl get pods -l app=flask-app -w
# change spec.replicas to 5 in the file, then:
kubectl apply -f k8s/replication-controller.yaml
kubectl get rc flask-rc
```

## Part 6: Rolling update

`flask-deployment.yaml` uses `RollingUpdate` with `maxUnavailable: 1` and `maxSurge: 1`.

```bash
docker build --build-arg APP_VERSION=v2 -t YOUR_DOCKERHUB_USERNAME/todo-flask:v2 ./app
docker push YOUR_DOCKERHUB_USERNAME/todo-flask:v2

kubectl set image deployment/flask-app flask-app=YOUR_DOCKERHUB_USERNAME/todo-flask:v2
kubectl rollout status deployment/flask-app
kubectl get pods -l app=flask-app -w        # old pods are replaced one at a time
kubectl rollout history deployment/flask-app

# The page header now shows "Version: v2"
kubectl rollout undo deployment/flask-app   # roll back if needed
```

To make v2 visibly different, edit `app/templates/index.html` before building it, for example by changing the heading.

## Part 7: Health monitoring

- Liveness probe: `GET /health` every 10s. After 3 failures, the kubelet restarts the container.
- Readiness probe: `GET /ready` every 5s, which pings MongoDB. After 2 failures, the pod is taken out of the Service so it gets no traffic.

```bash
kubectl describe pod <flask-app-pod-name>   # shows the Liveness/Readiness settings

# Liveness failure: break one pod and watch it restart
kubectl port-forward pod/<flask-app-pod-name> 8080:5000 &
curl localhost:8080/fail
kubectl get pods -l app=flask-app -w        # RESTARTS goes up by 1 after about 30s
kubectl describe pod <flask-app-pod-name>   # Events: "Liveness probe failed ... will be restarted"

# Readiness failure: take MongoDB away
kubectl scale deployment mongo --replicas=0
kubectl get pods -l app=flask-app -w        # READY becomes 0/1, pods are not restarted
kubectl get endpoints flask-service         # no endpoints
kubectl scale deployment mongo --replicas=1 # pods become ready again
```

## Part 8 (extra credit): Prometheus and Slack alerts

1. In Slack, create a private channel (for example `#k8s-alerts`) in your own workspace, not a class channel. Add an Incoming Webhook app and copy its URL.
2. Put the webhook URL and channel name into `monitoring/values.yaml`. Do not commit the real URL.
3. Install the stack and the rules:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace -f monitoring/values.yaml
kubectl apply -f monitoring/alert-rules.yaml
kubectl get pods -n monitoring
```

4. Trigger alerts and check Slack:

```bash
kubectl delete pod <flask-app-pod-name>     # TodoReplicasUnavailable
curl localhost:8080/fail                    # via port-forward: TodoPodRestarting
kubectl scale deployment mongo --replicas=0 # TodoPodNotReady
```

5. View the alerts in the UIs:

```bash
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090   # http://localhost:9090/alerts
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-alertmanager 9093 # http://localhost:9093
```

## Screenshots for the report

- `docker compose ps` and the app at `localhost:8080`
- Docker Hub repository page with the `v1` and `v2` tags
- Minikube: `kubectl get pods,svc,pvc` and the app in the browser
- Pod recovery: before and after `kubectl delete pod`
- EKS: `kubectl get nodes`, `kubectl get svc` with the ELB hostname, and the app in the browser
- `kubectl get rs` and scaling output
- `kubectl rollout status` and the page showing `v2`
- `kubectl describe pod` events showing the liveness restart and readiness failure
- (Extra credit) Prometheus alerts page and the Slack message

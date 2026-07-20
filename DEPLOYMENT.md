# Deployment Guide

This is a click-by-click, command-by-command walkthrough of taking this repo
from "code on your laptop" to "live, publicly reachable, auto-deploying on
every push." Every step includes what you should see when it worked, and
what to do if it didn't.

**Total time:** 45-90 minutes the first time, mostly waiting on Oracle's
account approval. Every push after this takes zero manual steps.

**Before you start, have ready:**
- A GitHub account
- A credit or debit card (for Oracle identity verification only - see 1.1)
- An SSH key pair on your machine. Check if you already have one:
  ```bash
  ls ~/.ssh/id_rsa.pub 2>/dev/null || ls ~/.ssh/id_ed25519.pub 2>/dev/null
  ```
  If neither exists, create one:
  ```bash
  ssh-keygen -t ed25519 -C "taskflow-deploy" -f ~/.ssh/id_ed25519
  # press Enter through the prompts (empty passphrase is fine for this use case)
  ```

---

## Part 1 — Oracle Cloud Account and VM

### 1.1 Sign up

1. Go to **https://www.oracle.com/cloud/free/**
2. Click **Start for free**
3. Fill in email, verify it (check your inbox for a code)
4. Fill in your address and **payment verification** - Oracle charges nothing, but requires a card to confirm you're a real person and not a bot. You will not be billed unless you explicitly upgrade the account later.
5. Choose your **Home Region** carefully - you cannot easily change this later, and ARM capacity availability varies significantly by region. Regions like `us-ashburn-1`, `uk-london-1`, and `eu-frankfurt-1` tend to have better free-tier ARM availability than others.
6. Submit and wait for account activation. This is usually instant but can take up to a few hours if Oracle's fraud check flags your signup for manual review - if that happens, check your email for a follow-up from Oracle support.

**Checkpoint:** you can log in at `https://cloud.oracle.com` and see the Console dashboard.

### 1.2 Create the VM instance

1. In the Console, use the hamburger menu (top-left) → **Compute → Instances**
2. Click **Create instance**
3. **Name:** `taskflow-prod` (or anything - purely cosmetic)
4. **Placement:** leave the default availability domain
5. **Image and shape** → click **Edit**
   - Image: click **Change image** → select **Canonical Ubuntu** → **24.04** → click **Select image**
   - Shape: click **Change shape** → select the **Ampere** tab → choose `VM.Standard.A1.Flex`
   - Set the sliders: **2 OCPU / 12 GB memory** (this is the current free-tier allowance as of mid-2026; if your account shows a higher allowance available, e.g. 4 OCPU/24GB, you can use that instead)
   - Click **Select shape**
6. **Networking:** leave defaults (it will create a new VCN for you automatically if this is your first instance) - just confirm **"Assign a public IPv4 address"** is checked, or you won't be able to reach it from the internet
7. **Add SSH keys:** select **Paste public keys**, then paste the contents of your public key:
   ```bash
   cat ~/.ssh/id_ed25519.pub
   ```
   Paste the entire output (starts with `ssh-ed25519` or `ssh-rsa`) into the box.
8. **Boot volume:** leave the default (50GB is plenty)
9. Click **Create**

**Checkpoint:** the instance list shows `taskflow-prod` with a status that moves from `PROVISIONING` → `RUNNING` within 1-3 minutes. Click into it and copy the **Public IP address** shown on the instance detail page - you'll need it constantly from here on. Write it down or export it:
```bash
export VM_IP=<paste-the-ip-here>
```

### 1.3 Open the firewall - Oracle's cloud-level Security List

This is the single most common point of failure, so do it carefully.

1. On the instance detail page, click the link under **Primary VNIC** → **Subnet** (it'll say something like `subnet-xxxxx`)
2. Click into the subnet, then click the **Default Security List** link
3. Click **Add Ingress Rules**
4. Fill in:
   - **Source Type:** CIDR
   - **Source CIDR:** `0.0.0.0/0`
   - **IP Protocol:** TCP
   - **Destination Port Range:** `8000`
   - **Description:** `TaskFlow API`
5. Click **Add Ingress Rules**

**Checkpoint:** the Default Security List's ingress rules table now shows a row allowing TCP port 8000 from `0.0.0.0/0`, alongside the pre-existing rule for port 22 (SSH).

*(If you plan to add HTTPS later via Part 4 below, also add ingress rules here for ports 80 and 443 now, so you don't have to come back.)*

---

## Part 2 — Prepare the Server

### 2.1 Connect over SSH

```bash
ssh ubuntu@$VM_IP
```
First connection asks to confirm the host fingerprint - type `yes`.

**If this hangs or times out:** it's almost always Part 1.3 (the Security List rule) - but that rule was for port 8000, and SSH needs port 22, which Oracle opens by default. If SSH itself is timing out, double check:
- You copied the IP correctly
- The instance status is `RUNNING`, not still `PROVISIONING`
- You're using the username `ubuntu` (not `root` or `opc` - Ubuntu images use `ubuntu`)

**Checkpoint:** your terminal prompt changes to something like `ubuntu@taskflow-prod:~$`

### 2.2 Update the system and install Docker

```bash
sudo apt update && sudo apt upgrade -y
```
This can take a couple of minutes on first boot.

```bash
curl -fsSL https://get.docker.com | sudo sh
```
This runs Docker's official install script - takes about a minute, prints a lot of output ending in something like `To run Docker as a non-privileged user...`.

```bash
sudo usermod -aG docker $USER
newgrp docker
```
The second command refreshes your current shell's group membership without needing to log out. If it doesn't seem to take effect, actually log out (`exit`) and `ssh ubuntu@$VM_IP` back in.

Verify:
```bash
docker --version
docker compose version
docker run hello-world
```
**Checkpoint:** the third command downloads a tiny test image and prints `Hello from Docker!` along with an explanation paragraph. If you get a permission error instead, the group change from `usermod` hasn't taken effect yet - log out and back in.

### 2.3 Open the OS-level firewall too

Oracle's Ubuntu images ship with `iptables` rules that block inbound traffic by default, on top of the cloud Security List you configured in 1.3. Both layers need to allow port 8000.

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save
```
If `netfilter-persistent` isn't found:
```bash
sudo apt install -y iptables-persistent
sudo netfilter-persistent save
```

**Checkpoint:** run `sudo iptables -L INPUT -n | grep 8000` - you should see a line with `ACCEPT` and `dpt:8000`.

---

## Part 3 — Get the Code Running

### 3.1 Push your local copy to GitHub first

Do this from **your own machine**, not the VM.

```bash
cd taskflow    # wherever you unzipped/extracted the project
git init
git add .
git status      # sanity check: .env should NOT be listed (it's in .gitignore) - if it is, stop and check .gitignore
git commit -m "Initial commit"
git branch -M main
```

Create an empty repository on GitHub (github.com → **New repository** → name it `taskflow` → do **not** initialize with a README, since you already have one → **Create repository**). GitHub will show you a remote URL - use it:

```bash
git remote add origin https://github.com/<your-username>/taskflow.git
git push -u origin main
```

**Checkpoint:** refresh the GitHub repo page in your browser - your files are there.

### 3.2 Clone it onto the VM

Back in your SSH session:
```bash
cd ~
git clone https://github.com/<your-username>/taskflow.git
cd taskflow
```

### 3.3 Create the real .env file

```bash
cp .env.example .env
```

Generate a real secret (don't skip this - the example value is public, in a public repo, and anyone could forge tokens against it):
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Copy the output. Now edit the file:
```bash
nano .env
```
Set:
```
JWT_SECRET=<paste the generated value>
GHCR_IMAGE=ghcr.io/<your-github-username>/taskflow:latest
```
Leave the DB/Redis/Kafka URLs as-is - `docker-compose.yml` overrides those with the correct in-network container hostnames regardless of what's in `.env`.

Save and exit nano: `Ctrl+O`, `Enter`, `Ctrl+X`.

### 3.4 First manual deploy

This proves the stack works before you wire up automation - much easier to debug interactively than through GitHub Actions logs.

```bash
docker compose up -d --build
```
This will take a few minutes the first time - it's building the API image and pulling Postgres, Redis, and Redpanda images.

Watch it come up:
```bash
docker compose ps
```
**Checkpoint:** you should see 5 services (`db`, `redis`, `redpanda`, `api`, `consumer`) all with a `State` of `running` or `healthy`. If any show `Restarting` repeatedly, jump to the Troubleshooting section below.

Check each layer individually:
```bash
# Postgres is accepting connections
docker compose exec db pg_isready -U taskflow

# Redis is responding
docker compose exec redis redis-cli ping
# should print: PONG

# Redpanda cluster is healthy
docker compose exec redpanda rpk cluster health
# should include: Healthy: true

# The API itself
curl http://localhost:8000/health
# should print: {"status":"ok","environment":"development"}
```

From your **own machine** (not the VM), confirm it's reachable from the outside world:
```bash
curl http://$VM_IP:8000/health
```
**Checkpoint:** same JSON response. If this hangs while `localhost:8000` worked fine on the VM, it's a firewall issue - re-check Parts 1.3 and 2.3, in that order.

Open `http://<your-vm-ip>:8000/docs` in a browser - you should see the interactive Swagger UI listing every endpoint.

---

## Part 4 — Automate It (CI/CD)

### 4.1 Create a dedicated deploy key (don't reuse your personal SSH key)

Best practice: GitHub Actions gets its own key pair, scoped only to deploying, so if it ever leaked it wouldn't give access to anything else you use that key for.

On **your own machine**:
```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/taskflow_deploy_key -N ""
```
This creates two files: `taskflow_deploy_key` (private) and `taskflow_deploy_key.pub` (public).

Authorize the public half on the VM:
```bash
cat ~/.ssh/taskflow_deploy_key.pub | ssh ubuntu@$VM_IP "cat >> ~/.ssh/authorized_keys"
```

Test it works before moving on:
```bash
ssh -i ~/.ssh/taskflow_deploy_key ubuntu@$VM_IP "echo it works"
```
**Checkpoint:** prints `it works` with no password/passphrase prompt.

### 4.2 Add GitHub Actions secrets

GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Add three:

| Name | Value |
|---|---|
| `SSH_HOST` | Your VM's IP (the `$VM_IP` value) |
| `SSH_USER` | `ubuntu` |
| `SSH_PRIVATE_KEY` | Output of `cat ~/.ssh/taskflow_deploy_key` on your machine - the **entire** file contents, including the `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END...-----` lines |

**Checkpoint:** the Secrets page lists all three (values are hidden after saving, which is expected - GitHub never shows them again).

### 4.3 Let GHCR pushes/pulls work

The CD workflow pushes images to GitHub Container Registry using the automatically-provided `GITHUB_TOKEN` - no setup needed for that side. But the VM needs to be able to *pull* them:

1. GitHub → your profile picture → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**
2. Name it `taskflow-ghcr-pull`, expiration your choice, check only the **read:packages** scope
3. Generate, copy the token (starts with `ghp_`) - you won't see it again

On the VM:
```bash
echo "<paste the ghp_ token>" | docker login ghcr.io -u <your-github-username> --password-stdin
```
**Checkpoint:** prints `Login Succeeded`.

Also, by default GHCR packages are private. After your first CD run pushes an image (next step), go to your GitHub profile → **Packages** → click `taskflow` → **Package settings** → scroll to **Danger Zone** → **Change visibility** → set to **Public** (simplest option for a personal project) - or, if you'd rather keep it private, the `docker login` step above is enough since the VM is already authenticated.

### 4.4 Trigger the pipeline

```bash
# from your own machine, in the local taskflow/ folder
git commit --allow-empty -m "Trigger first CI/CD run"
git push origin main
```

Go to your GitHub repo → **Actions** tab. You'll see two workflow runs appear:

1. **CI** starts immediately. Click into it and watch the steps: dependency install, `ruff check`, Alembic migration against a real Postgres service container, the Redpanda broker starting, the full pytest suite (18 unit/Kafka tests + 1 integration test), and finally a Docker build sanity check. This takes roughly 2-4 minutes.
2. Once CI shows a green check, **CD** triggers automatically (it's configured to run only `on: workflow_run` after CI succeeds). Click into it: it builds the production image, pushes to `ghcr.io/<you>/taskflow`, then SSHes into your VM and runs the deploy script.

**Checkpoint:** both workflows show green checkmarks. If CD's SSH step fails, see Troubleshooting below.

### 4.5 Verify the automated deploy actually updated the server

```bash
ssh -i ~/.ssh/taskflow_deploy_key ubuntu@$VM_IP
cd ~/taskflow
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml images api
```
**Checkpoint:** the `api` service's image tag matches a recent GHCR push (check the Image ID/tag against what CD just pushed, visible in the CD workflow logs under the "Build and push image" step).

---

## Part 5 — End-to-End Proof

Run this from your own machine to prove every layer is actually wired together, not just individually running:

```bash
BASE=http://$VM_IP:8000

curl -s -X POST $BASE/auth/signup -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"secret123"}' | python3 -m json.tool

TOKEN=$(curl -s -X POST $BASE/auth/login \
  -d "username=you@example.com&password=secret123" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST $BASE/tasks -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Deployment proof"}' | python3 -m json.tool

sleep 2

curl -s $BASE/stats | python3 -m json.tool
```

**Checkpoint:** the final response shows `"tasks_created_total": 1` (or higher, if you'd already created tasks earlier). That number only exists because `app/consumer.py`, running as its own container, actually received and processed a real Kafka event published by the API container - this is the proof the whole chain works, not just each piece in isolation.

---

## Troubleshooting

**A container keeps restarting (`docker compose ps` shows `Restarting`)**
```bash
docker compose logs <service-name> --tail 50
```
Common causes: `api` restarting almost always means it's failing to reach the database (check `db` is healthy first, since `api` depends on it) or a migration error (check the log for an Alembic traceback).

**`docker compose up` fails with "no space left on device"**
The free-tier boot volume can fill up from repeated image builds. Clean up:
```bash
docker system prune -af --volumes   # WARNING: removes stopped containers and unused images/volumes
```

**Port 8000 unreachable from outside, but works via `curl localhost:8000` on the VM itself**
This is always one of the two firewall layers (Part 1.3 or Part 2.3). Re-check both. To confirm which layer is blocking, run this from your own machine:
```bash
nc -zv $VM_IP 8000
```
If it hangs completely with no response, it's usually the Oracle Security List (cloud layer, checked first by the network path). If it gets a `Connection refused` quickly, the cloud layer is open but the OS-level `iptables` or the container itself isn't listening.

**GitHub Actions CD step fails at "Deploy to production VM over SSH" with a connection or auth error**
- Re-verify the `SSH_HOST` secret exactly matches your current VM IP (Oracle free-tier IPs can occasionally change if the instance is stopped and restarted - if that happened, update the secret)
- Re-verify `SSH_PRIVATE_KEY` was pasted completely, including the BEGIN/END lines and no extra leading/trailing whitespace
- Confirm the matching public key is still in `~/.ssh/authorized_keys` on the VM: `cat ~/.ssh/authorized_keys` should contain a line ending in `github-actions-deploy`

**CD step fails trying to pull the image ("denied" or "unauthorized")**
Almost always means the `docker login` from Part 4.3 either wasn't run on the VM, or the personal access token expired. Re-run the `docker login` command with a fresh token.

**Alembic migration fails during CI ("relation already exists" or similar)**
This usually means the test database from a previous CI run wasn't cleaned up properly - CI containers are ephemeral and shouldn't have this problem, but if you see it, it's worth checking whether `services.postgres` in `ci.yml` has a fresh volume each run (it does, by default, since GitHub Actions service containers don't persist between runs) - report this as a genuine bug if it happens, since it shouldn't.

**The Redpanda broker step in CI times out waiting for "Healthy: true"**
GitHub-hosted runners occasionally have slow Docker pulls. Re-run the failed job (Actions tab → the failed run → **Re-run failed jobs**) - this is almost always transient.

---

## Ongoing Operations

**Redeploy after a code change:** just `git push origin main` - CI and CD run automatically, no manual server steps.

**View live logs on the server:**
```bash
ssh ubuntu@$VM_IP
cd ~/taskflow
docker compose logs -f api        # API request logs
docker compose logs -f consumer   # Kafka consumer activity
```

**Roll back to a previous version:** every image CD pushes is tagged with both `latest` and the exact commit SHA. To roll back:
```bash
ssh ubuntu@$VM_IP
cd ~/taskflow
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull  # no-op if already latest
# manually run a specific SHA if needed:
docker run -d --name api-rollback ghcr.io/<you>/taskflow:<old-sha> ...
```
For a cleaner rollback workflow, `git revert` the bad commit and push - that triggers a normal forward deploy of the previous known-good code, which is generally safer than manually juggling image tags.

**Back up the database:**
```bash
docker compose exec db pg_dump -U taskflow taskflow > backup-$(date +%F).sql
```
Copy it off the VM regularly (`scp ubuntu@$VM_IP:~/taskflow/backup-*.sql .`) - a single free-tier VM has no redundancy, so this file is your only real safety net.

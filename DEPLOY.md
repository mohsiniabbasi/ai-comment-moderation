# Deploy — ai-comment-moderation → moderation.pivotbureau.com

Same pattern as the other Pivot Bureau demos (leads / reports / grants / inbox):
Docker image on the Hetzner box `188.245.208.99`, reverse-proxied by Caddy, one
grey-cloud Cloudflare A record so Caddy's ACME HTTP-01 can issue the cert.

## 0. Push to GitHub (public) — Mohsan
```bash
# in C:\Users\User\ai-comment-moderation  (already git-init'd, 2 commits)
gh repo create mohsiniabbasi/ai-comment-moderation --public --source=. --remote=origin --push
# or, if the repo already exists:
git remote add origin https://github.com/mohsiniabbasi/ai-comment-moderation.git
git push -u origin master
```
Secret-scan is clean — no keys in the repo (LLM keys come only from env at runtime).

## 1. Cloudflare DNS — Mohsan (must be GREY cloud / DNS-only)
Add an **A record**: `moderation` → `188.245.208.99`, **DNS only (grey cloud)** so
Caddy can complete the HTTP-01 challenge. Can switch to orange/proxied after the
cert issues.

## 2. Build & run on the server
```bash
ssh root@188.245.208.99 -i ~/.ssh/pivot_bureau_deploy
mkdir -p /opt/demos && cd /opt/demos
git clone https://github.com/mohsiniabbasi/ai-comment-moderation.git
cd ai-comment-moderation
docker build -t moderation-demo:latest .
docker run -d --name moderation-demo --restart unless-stopped \
  --network pivot-bureau-app_web moderation-demo:latest
# optional live LLM (cheap): add  -e GEMINI_API_KEY=...  (gemini-2.5-flash-lite)
#                            or  -e ANTHROPIC_API_KEY=... (claude-haiku-4-5)
```

## 3. Caddy — add the subdomain block
Edit `/opt/pivot-bureau-app/Caddyfile` (back it up first, like the other demos):
```bash
cp /opt/pivot-bureau-app/Caddyfile /opt/pivot-bureau-app/Caddyfile.bak.premoderation.$(date +%s)
```
Add:
```
moderation.pivotbureau.com {
    reverse_proxy moderation-demo:8000
}
```
Validate + reload (from the Caddy container/compose, same as before):
```bash
cd /opt/pivot-bureau-app
docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile
docker compose exec caddy caddy reload  --config /etc/caddy/Caddyfile
```

## 4. Verify
```bash
curl -I https://moderation.pivotbureau.com        # expect HTTP 200 once cert issues
curl -I https://api.pivotbureau.com               # confirm still 200 (unaffected)
```

## Redeploy after a repo push
```bash
cd /opt/demos/ai-comment-moderation && git pull \
  && docker build -t moderation-demo:latest . \
  && docker rm -f moderation-demo \
  && docker run -d --name moderation-demo --restart unless-stopped \
     --network pivot-bureau-app_web moderation-demo:latest
```

# Dynamic Application Gateway & Web Terminal Guide

DeepSeek Harness (DSH) in this deployment includes an integrated **Dynamic Reverse Proxy Gateway** and **Interactive Web Terminal** running in front of the DSH engine.

This document details the dual routing strategies (Subdomain vs Path-based), WebSocket upgrades, named port aliases, and Web Terminal access.

---

## 🏛️ Gateway Routing Topology

```
                       User Browser
                            │
               ┌────────────┴────────────┐
               │                         │
     Option 1: Subdomain       Option 2: Path Proxy
     dsh-8501.example.com      dsh.example.com/proxy/8501/
               │                         │
               └────────────┬────────────┘
                            │ Port 3080
                            ▼
   ┌────────────────────────────────────────────────────────┐
   │         Enterprise Auth Proxy (scripts/auth_proxy.js)   │
   │  • Validates session cookie (dsh_auth)                 │
   │  • Extracts target port (subdomain or URL path)        │
   │  • Handles WebSocket / Upgrade headers                 │
   └───────────┬──────────────┬──────────────┬──────────────┘
               │              │              │
      Port 3081│     Port 7681│      Port N  │
               ▼              ▼              ▼
          ┌────────┐     ┌────────┐     ┌────────┐
          │  DSH   │     │  ttyd  │     │ Custom │
          │  Web   │     │Terminal│     │  Apps  │
          │ Engine │     │(bash)  │     │(Flask, │
          │        │     │        │     │Stream- │
          │        │     │        │     │ lit..) │
          └────────┘     └────────┘     └────────┘
```

---

## 🚀 Routing Option 1: Wildcard Subdomain Routing (Recommended for SPAs)

Subdomain routing proxies traffic based on the hostname prefix:
`https://<tenant>-<port>.<domain>` or `https://<tenant>-<alias>.<domain>`

### Examples:
| Subdomain | Forwarded Target Inside Container | Typical Application | Default Resolution |
| :--- | :--- | :--- | :--- |
| `dsh.example.com` | `http://127.0.0.1:3081/` | DSH Web User Interface | Root Host ➔ DSH Engine |
| `dsh-app.example.com` | Customizable via `.ports.json` | General Application Alias | **Port 3081** (Fallback to DSH UI) or custom port via `{"app": 5000}` |
| `dsh-terminal.example.com` | `http://127.0.0.1:7681/` | Interactive bash web terminal | Built-in Alias `'terminal'` ➔ 7681 |
| `dsh-8501.example.com` | `http://127.0.0.1:8501/` | Streamlit Dashboard | Direct Numeric Port 8501 |
| `dsh-8000.example.com` | `http://127.0.0.1:8000/` | FastAPI / Uvicorn Server | Direct Numeric Port 8000 |
| `dsh-8080.example.com` | `http://127.0.0.1:8080/` | EDA / Web Microservice | Direct Numeric Port 8080 |
| `dsh-5000.example.com` | `http://127.0.0.1:5000/` | Flask / Gradio Application | Direct Numeric Port 5000 |
| `dsh-3000.example.com` | `http://127.0.0.1:3000/` | Next.js / React / Vite Dev Server | Direct Numeric Port 3000 |
| `dsh-7681.example.com` | `http://127.0.0.1:7681/` | ttyd Web Terminal (by port) | Direct Numeric Port 7681 |

### Why use Subdomain Routing?
Modern single-page applications (Vite, Next.js, Streamlit, Grafana) frequently load assets from absolute root paths (e.g., `<script src="/_assets/vendor.js">`). Path-based proxies break unless the app is specially configured with a subpath prefix. Subdomain routing provides 100% transparent root-relative URL routing.

### Multi-Tenant Shared Domain Consideration:
On a shared corporate domain (where multiple tenants like `dsh`, `dsh2`, `dsh3` run concurrently), standard Kubernetes Ingress does not allow partial wildcards (`dsh-*`). In this scenario, either declare explicit 1-level subdomains in the Ingress manifest (as shown above) or utilize **Option 2 (Path Proxy)**.

---

## 🔀 Routing Option 2: Dynamic Path-Based Proxy

Dynamic path proxying allows on-the-fly port forwarding without adding new DNS hostnames:
`https://<tenant>.<domain>/proxy/<port>/`

### Examples:
- `https://dsh.example.com/proxy/8501/` ➔ `http://127.0.0.1:8501/`
- `https://dsh.example.com/proxy/5000/` ➔ `http://127.0.0.1:5000/`
- `https://dsh.example.com/proxy/terminal/` ➔ `http://127.0.0.1:7681/`

### Features:
1. **Dynamic Port Discovery**: Any port between `1` and `65535` is forwarded instantly upon request.
2. **Trailing Slash Auto-Redirect**: Accessing `/proxy/5000` automatically redirects to `/proxy/5000/` to ensure relative resource links resolve properly.
3. **HTML Base Injection**: The proxy rewrites root asset paths where necessary to assist non-root hosted webapps.

---

## ⚡ WebSocket & Streaming Upgrades

The proxy transparently handles HTTP `Upgrade: websocket` requests for:
- **Streamlit** (interactive state updates and widget events)
- **Vite & Next.js HMR** (Hot Module Replacement live updates)
- **ttyd Web Terminal** (bidirectional xterm.js terminal stream)
- **FastAPI / Tornado WebSockets**

---

## 🏷️ Named Port Aliases (`/workspace/.ports.json`)

To use friendly names instead of port numbers, create `/workspace/.ports.json`:

```json
{
  "dashboard": 8501,
  "api": 8000,
  "eda": 8080,
  "chat": 3000
}
```

Once defined, requests to `https://dsh-dashboard.example.com` or `https://dsh.example.com/proxy/dashboard/` automatically resolve to port `8501`.

---

## 🖥️ Interactive Web Terminal (`ttyd`)

The container bundles `ttyd` (xterm.js Web Terminal) running on `127.0.0.1:7681`.

### Access:
- **Via Subdomain**: `https://dsh-terminal.example.com`
- **Via Path Proxy**: `https://dsh.example.com/proxy/terminal/`
- **Via Port**: `https://dsh-7681.example.com` or `https://dsh.example.com/proxy/7681/`

### Security:
`ttyd` is bound strictly to `127.0.0.1` and can **only** be accessed through the authenticated session cookie managed by `auth_proxy.js`.

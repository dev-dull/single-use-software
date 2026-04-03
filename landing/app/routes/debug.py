"""Debug routes — diagnostics for the build pod pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug")


@router.get("/build-chain/{team}/{app_slug}")
async def debug_build_chain(
    team: str,
    app_slug: str,
) -> JSONResponse:
    """Run a full diagnostic of the build chain and report each step."""
    results: dict[str, Any] = {"steps": []}

    def step(name: str, status: str, detail: str = "") -> None:
        results["steps"].append({"name": name, "status": status, "detail": detail})
        logger.info("DEBUG [%s] %s: %s", name, status, detail)

    # Step 1: K8s connection
    try:
        from ..pods import BuildPodManager
        pm = BuildPodManager()
        step("k8s_connection", "ok", f"namespace={pm._namespace}, image={pm._image}")
    except Exception as e:
        step("k8s_connection", "fail", str(e))
        return JSONResponse(results)

    # Step 2: Check existing build pods
    try:
        pods = pm.list_build_pods()
        step("list_pods", "ok", f"found {len(pods)} build pods")
        for p in pods:
            step(f"pod_{p['name']}", "info",
                 f"phase={p['phase']}, ip={p.get('pod_ip')}, labels={p.get('labels')}")
    except Exception as e:
        step("list_pods", "fail", str(e))

    # Step 3: Create a test build pod
    pod_name = None
    pod_ip = None
    try:
        pod_name = pm.create_build_pod(
            user_id="debug-test",
            app_slug=app_slug,
            branch=f"debug-test/{app_slug}/test",
        )
        step("create_pod", "ok", f"pod_name={pod_name}")
    except Exception as e:
        step("create_pod", "fail", str(e))
        return JSONResponse(results)

    # Step 4: Wait for pod to be Running with an IP
    try:
        for i in range(30):
            await asyncio.sleep(2)
            info = pm.get_build_pod(pod_name)
            if info is None:
                step("wait_pod", "fail", "pod disappeared")
                return JSONResponse(results)
            phase = info.get("phase", "Unknown")
            pod_ip = info.get("pod_ip")
            if phase == "Running" and pod_ip:
                step("wait_pod", "ok", f"phase={phase}, ip={pod_ip}, waited={i*2}s")
                break
            if phase in ("Failed", "Error"):
                step("wait_pod", "fail", f"phase={phase} after {i*2}s")
                # Get logs
                try:
                    from kubernetes import client
                    core = client.CoreV1Api()
                    log = core.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=pm._namespace,
                        tail_lines=20,
                    )
                    step("pod_logs", "info", log)
                except Exception as le:
                    step("pod_logs", "fail", str(le))
                return JSONResponse(results)
        else:
            step("wait_pod", "timeout", f"last phase={phase}, ip={pod_ip}")
            return JSONResponse(results)
    except Exception as e:
        step("wait_pod", "fail", str(e))
        return JSONResponse(results)

    # Step 5: Check pod logs
    try:
        from kubernetes import client
        core = client.CoreV1Api()
        log = core.read_namespaced_pod_log(
            name=pod_name,
            namespace=pm._namespace,
            tail_lines=30,
        )
        step("pod_logs", "ok", log)
    except Exception as e:
        step("pod_logs", "fail", str(e))

    # Step 6: Test HTTP to ttyd
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{pod_ip}:8080/")
            step("ttyd_http", "ok", f"status={resp.status_code}, content_length={len(resp.content)}")
    except Exception as e:
        step("ttyd_http", "fail", str(e))

    # Step 7: Test WebSocket to ttyd
    try:
        import websockets
        ws = await websockets.connect(
            f"ws://{pod_ip}:8080/ws",
            subprotocols=["tty"],
            open_timeout=5,
        )
        step("ttyd_ws_connect", "ok", f"subprotocol={ws.subprotocol}")

        # Send auth + resize
        await ws.send(json.dumps({"AuthToken": ""}))
        await ws.send(struct.pack("!BHH", 1, 80, 24))

        messages = []
        for _ in range(3):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                messages.append(repr(msg[:200]))
            except asyncio.TimeoutError:
                break
        await ws.close()
        step("ttyd_ws_data", "ok", f"received {len(messages)} messages: {messages}")
    except Exception as e:
        step("ttyd_ws_data", "fail", str(e))

    # Step 8: Test our HTTP proxy to ttyd
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"http://localhost:8000/build/{team}/{app_slug}/terminal/?pod_ip={pod_ip}"
            )
            step("proxy_http", "ok", f"status={resp.status_code}, content_length={len(resp.content)}")
    except Exception as e:
        step("proxy_http", "fail", str(e))

    # Step 9: Test our WebSocket proxy
    try:
        import websockets
        ws = await websockets.connect(
            f"ws://localhost:8000/build/{team}/{app_slug}/terminal/ws?pod_ip={pod_ip}",
            subprotocols=["tty"],
            open_timeout=5,
        )
        step("proxy_ws_connect", "ok", f"subprotocol={ws.subprotocol}")

        await ws.send(json.dumps({"AuthToken": ""}))
        await ws.send(struct.pack("!BHH", 1, 80, 24))

        messages = []
        for _ in range(3):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                messages.append(repr(msg[:200]))
            except asyncio.TimeoutError:
                break
        await ws.close()
        step("proxy_ws_data", "ok" if messages else "fail",
             f"received {len(messages)} messages: {messages}")
    except Exception as e:
        step("proxy_ws_data", "fail", str(e))

    # Cleanup: delete the test pod
    try:
        pm.delete_build_pod(pod_name)
        step("cleanup", "ok", f"deleted {pod_name}")
    except Exception as e:
        step("cleanup", "fail", str(e))

    # Summary
    failures = [s for s in results["steps"] if s["status"] == "fail"]
    results["summary"] = {
        "total_steps": len(results["steps"]),
        "failures": len(failures),
        "all_ok": len(failures) == 0,
    }

    return JSONResponse(results)


@router.get("/env")
async def debug_env() -> JSONResponse:
    """Show relevant environment variables."""
    keys = [
        "SUS_WORKLOADS_NAMESPACE", "SUS_BUILD_IMAGE", "SUS_BUILD_IMAGE_PULL_POLICY",
        "SUS_APPS_ROOT", "SUS_SKILLS_DIR", "SUS_GIT_REPO_URL", "SUS_CONFIG_PATH",
    ]
    return JSONResponse({k: os.environ.get(k, "(not set)") for k in keys})

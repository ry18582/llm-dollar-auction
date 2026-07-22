#!/usr/bin/env python3
"""Expose a loopback-only server on one specific network interface.

Most dev servers bind 127.0.0.1, which is correct — it is the safe default.
This forwards a chosen interface:port to that loopback port, so another machine
can reach it *without* the app being changed to bind 0.0.0.0.

Why a forwarder rather than "just bind 0.0.0.0":

  - 0.0.0.0 binds *every* interface, including ones you did not think about.
    Binding one address is the narrower, more deliberate choice.
  - It works for apps with no --host flag at all.
  - It is reversible: kill the forwarder and the app is loopback-only again,
    with no config left behind to forget about.

Stdlib only. No dependencies.

    python3 share_port.py --port 8765
    python3 share_port.py --port 8765 --bind 10.8.0.5
    python3 share_port.py --port 3000 --bind 10.8.0.5 --allow 10.8.0.0/24

Security: this adds NO authentication. Whatever the app exposes, every host
that can reach the bind address can also reach — including any "run this" or
"delete that" button. Prefer a VPN address over a LAN address, keep --allow
narrow, and stop the forwarder when you are done.
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
import subprocess
import sys
import threading
from datetime import datetime

BUFSIZE = 65536


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def interfaces() -> list[tuple[str, str]]:
    """[(ifname, ip), ...] for IPv4, via `ip` — no third-party dependency."""
    try:
        out = subprocess.run(
            ["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            found.append((parts[1], parts[3].split("/")[0]))
    return found


def classify(ifname: str, ip: str) -> str:
    """Label an address so the human choosing one knows what it reaches."""
    if ip.startswith("127."):
        return "loopback — this machine only"
    try:
        link = subprocess.run(
            ["ip", "-d", "link", "show", ifname], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        link = ""
    if "wireguard" in link:
        return "WireGuard VPN — reachable by VPN peers only (safest to share)"
    if "POINTOPOINT" in link:
        return "point-to-point tunnel"
    if ifname.startswith("eth") and ip.startswith("172."):
        return "WSL NAT — usually only the Windows host can reach this"
    if ip.startswith(("192.168.", "10.")) or ip.startswith("172."):
        return "private network — anyone on this network can reach it"
    return "PUBLIC address — do not expose an unauthenticated app here"


def list_interfaces() -> None:
    print("Available bind addresses:\n")
    for ifname, ip in interfaces():
        print(f"  {ip:<18} {ifname:<12} {classify(ifname, ip)}")
    print("\nPick the narrowest one that reaches the machine you want.")


def pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(BUFSIZE)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()


def allowed(peer_ip: str, networks: list) -> bool:
    if not networks:
        return True
    addr = ipaddress.ip_address(peer_ip)
    return any(addr in net for net in networks)


def serve(bind: str, port: int, target_host: str, target_port: int, networks: list) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((bind, port))
    except OSError as e:
        raise SystemExit(
            f"cannot bind {bind}:{port} — {e}\n"
            f"Is the address on this machine? Run with --list to see the options."
        ) from None
    listener.listen(64)

    log(f"forwarding  http://{bind}:{port}/  ->  {target_host}:{target_port}")
    if networks:
        log(f"allowing only: {', '.join(str(n) for n in networks)}")
    else:
        log("no --allow set: every host that can route to this address may connect")
    log("no authentication is added — Ctrl-C to stop")

    while True:
        try:
            client, addr = listener.accept()
        except KeyboardInterrupt:
            log("stopped")
            listener.close()
            return

        if not allowed(addr[0], networks):
            log(f"REFUSED {addr[0]} (not in --allow)")
            client.close()
            continue

        try:
            upstream = socket.create_connection((target_host, target_port), timeout=10)
        except OSError as e:
            log(f"{addr[0]} -> upstream unreachable: {e}")
            client.close()
            continue

        log(f"connect {addr[0]}")
        for a, b in ((client, upstream), (upstream, client)):
            threading.Thread(target=pump, args=(a, b), daemon=True).start()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, help="port the app listens on (and the port to expose)")
    p.add_argument("--bind", help="address to expose it on; omit to be shown the options")
    p.add_argument("--target", default="127.0.0.1", help="where the app is listening (default 127.0.0.1)")
    p.add_argument("--target-port", type=int, help="if the exposed port differs from the app's port")
    p.add_argument("--allow", default="", help="comma-separated CIDRs allowed to connect, e.g. 10.8.0.0/24")
    p.add_argument("--list", action="store_true", help="list bind addresses and exit")
    args = p.parse_args()

    if args.list or not args.port:
        list_interfaces()
        return 0

    if not args.bind:
        print("Choose an address with --bind. Options:\n")
        list_interfaces()
        return 2

    networks = []
    for chunk in filter(None, (c.strip() for c in args.allow.split(","))):
        networks.append(ipaddress.ip_network(chunk, strict=False))

    target_port = args.target_port or args.port

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(2)
    if probe.connect_ex((args.target, target_port)) != 0:
        print(
            f"warning: nothing is listening on {args.target}:{target_port} yet.\n"
            f"         Start the app first, or connections will be refused.",
            file=sys.stderr,
        )
    probe.close()

    serve(args.bind, args.port, args.target, target_port, networks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

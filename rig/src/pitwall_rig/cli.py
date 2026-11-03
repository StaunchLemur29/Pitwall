"""Command line entry point: ``pitwall-rig``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from aiohttp import web

from .browser import close_all, close_window, minimize_window, open_analysis, open_dashboard
from .config import Config, ConfigError, default_data_dir
from .input import InputService
from .rig import Rig
from .server import INPUT_KEY, ON_CONFIG_KEY, Hub, make_app
from .storage import Store

log = logging.getLogger("pitwall")

REPO_DASHBOARD = Path(__file__).resolve().parents[3] / "dashboard" / "dist"


def _make_adapter(game: str, args: argparse.Namespace, config: Config):
    install_dir = config["games"]["ac"]["install_dir"]
    if game == "ac":
        from .adapters.ac import AssettoCorsaAdapter

        return AssettoCorsaAdapter(install_dir=install_dir)
    if game == "demo":
        from .adapters.demo import DemoAdapter

        return DemoAdapter(time_scale=args.time_scale, seed=args.seed)
    if game == "replay":
        from .adapters.replay import ReplayAdapter

        if not args.replay:
            raise SystemExit("--replay FILE is required with --game replay")
        return ReplayAdapter(args.replay, time_scale=args.time_scale, install_dir=install_dir)
    raise SystemExit(f"Unknown game {game!r}")


def _fine_timers() -> None:
    """Windows ticks timers every ~15.6 ms by default, which turns a 60 Hz loop
    into an uneven ~30 Hz. Ask for 1 ms resolution while Pitwall runs."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:  # noqa: BLE001
            pass


def cmd_run(args: argparse.Namespace) -> None:
    _fine_timers()
    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
    try:
        config = Config(data_dir / "config.json")
    except ConfigError as e:
        raise SystemExit(str(e)) from e
    if not (data_dir / "config.json").exists():
        config.save()  # write defaults so they're easy to find and edit

    game = args.game or ("replay" if args.replay else config["game"])
    adapter = _make_adapter(game, args, config)
    store_path = data_dir / ("demo.sqlite" if game == "demo" else "pitwall.sqlite")
    store = Store(store_path)

    recorder = None
    if args.record:
        from .adapters.replay import Recorder

        rec_path = Path(args.record).expanduser().resolve()
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        recorder = Recorder(rec_path, adapter.game_id, adapter.capabilities)
        log.info("Recording telemetry to %s", rec_path)

    hub = Hub()
    rig = Rig(adapter, store, config, emit=hub.emit, recorder=recorder)
    static = Path(args.static) if args.static else REPO_DASHBOARD
    app = make_app(rig, hub, static_dir=static)

    def on_action(a: str, pressed: bool = True) -> None:
        loop = hub._loop
        if loop is not None:
            loop.call_soon_threadsafe(rig.action, a, pressed)

    def on_raw(ev) -> None:
        loop = hub._loop
        if loop is not None:
            loop.call_soon_threadsafe(rig.raw_input, ev)

    inp = InputService(lambda: config["bindings"], on_action, on_raw)
    app[INPUT_KEY] = inp
    app[ON_CONFIG_KEY] = inp.reload_keyboard

    async def start_input(_app: web.Application) -> None:
        inp.start()

    async def stop_input(_app: web.Application) -> None:
        inp.stop()
        adapter.close()
        if recorder:
            recorder.close()

    app.on_startup.append(start_input)
    app.on_cleanup.append(stop_input)

    host = "0.0.0.0" if args.lan else config["server"]["host"]
    port = args.port or config["server"]["port"]
    url = f"http://localhost:{port}/"
    log.info("Pitwall (%s) on %s", game, url)
    log.info("Laps are saved to %s", store_path)
    rig.on_open_analysis = lambda: open_analysis(url, config["display"])
    rig.on_close_window = close_window
    rig.on_minimize_window = minimize_window

    def shutdown() -> None:
        """The dashboard's Stop button: close windows, save everything, exit."""
        log.info("Stopping Pitwall (from the dashboard)")
        close_all()
        rig.keys.up()
        inp.stop()
        if recorder:
            recorder.close()
        adapter.close()
        store.close()
        os._exit(0)

    rig.on_shutdown = shutdown
    if args.open or config["display"]["open_browser"]:

        async def open_when_ready(_app: web.Application) -> None:
            # Open the window only once the server answers, so Chrome never
            # shows "localhost refused to connect".
            async def go() -> None:
                for _ in range(100):
                    try:
                        _r, w = await asyncio.open_connection("127.0.0.1", port)
                        w.close()
                        break
                    except OSError:
                        await asyncio.sleep(0.1)
                open_dashboard(url, config["display"])

            asyncio.get_running_loop().create_task(go())

        app.on_startup.append(open_when_ready)
    web.run_app(app, host=host, port=port, print=None, access_log=None)


def cmd_make_demo(args: argparse.Namespace) -> None:
    """Write a recording of the demo car (simulated, much faster than real time)."""
    from .adapters.demo import DemoAdapter
    from .adapters.replay import Recorder

    t = [0.0]
    demo = DemoAdapter(clock=lambda: t[0], seed=args.seed, start_in_pit_s=2.0)
    rec = Recorder(args.out, "demo", demo.capabilities)
    hz = 60
    for _ in range(int(args.seconds * hz)):
        t[0] += 1 / hz
        frame = demo.poll()
        rec.add(frame, demo.session())
    rec.close()
    print(f"Wrote {args.seconds:.0f}s of demo telemetry to {args.out}")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=os.environ.get("PITWALL_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    p = argparse.ArgumentParser(prog="pitwall-rig", description=__doc__)
    sub = p.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="Run the rig service and dashboard (default)")
    run.add_argument("--game", choices=["ac", "demo", "replay"], help="Override config.game")
    run.add_argument("--replay", help="Recording (.pwrec) to play with --game replay")
    run.add_argument("--record", help="Also save raw telemetry to this .pwrec file")
    run.add_argument("--time-scale", type=float, default=1.0, help="Demo/replay speed multiplier")
    run.add_argument("--seed", type=int, default=None)
    run.add_argument("--data-dir", help="Where settings and laps are stored")
    run.add_argument("--port", type=int)
    run.add_argument("--lan", action="store_true", help="Allow other devices on your network")
    run.add_argument("--static", help="Dashboard build directory")
    run.add_argument("--open", action="store_true", help="Open the dashboard on the vertical monitor")
    run.set_defaults(func=cmd_run)

    demo = sub.add_parser("make-demo", help="Generate a demo recording")
    demo.add_argument("out")
    demo.add_argument("--seconds", type=float, default=600)
    demo.add_argument("--seed", type=int, default=1)
    demo.set_defaults(func=cmd_make_demo)

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["run", *argv]
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

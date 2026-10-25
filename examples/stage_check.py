#!/usr/bin/env python3
"""
Stage bring-up. Run this before letting a campaign near the probe.

Walks through the checks in the order that matters:

  1. does the stage answer, and does M114 parse
  2. which way is up - the Z limit logic assumes Z increases away from the
     target, and everything downstream depends on that being right
  3. does a commanded move actually land where it was told
  4. do the Z guards refuse what they should
  5. does a small raster visit the right points

Nothing moves without a prompt, and nothing moves in Z by more than the step
you approve. Fit no probe for the first run.

    PYTHONPATH=. python3 examples/stage_check.py --dev /dev/snapy
"""
import argparse
import sys

from snapy import Stage, Position, ZLimitError, StageError

p = argparse.ArgumentParser()
p.add_argument('--dev', default="/dev/snapy")
p.add_argument('--baud', type=int, default=115200)
p.add_argument('--feed', type=int, default=500)
p.add_argument('--z-feed', type=int, default=100, dest="z_feed")
p.add_argument('--probe-fitted', action='store_true',
               help="reduce every test movement; assumes a probe is installed")
args = p.parse_args()

# With a probe fitted, keep every test movement small enough that a wrong
# assumption about direction cannot reach the board.
XY_TEST = 0.5 if args.probe_fitted else 2.0
Z_TEST = 0.2 if args.probe_fitted else 1.0

passed = []
failed = []


def check(name, fn):
    print("\n--- {} ---".format(name))
    try:
        fn()
    except Exception as e:
        print("  FAIL: {}: {}".format(type(e).__name__, e))
        failed.append(name)
    else:
        passed.append(name)


def confirm(prompt):
    reply = input("  {} [y/N] ".format(prompt)).strip().lower()
    if reply != "y":
        raise RuntimeError("declined by operator")


stage = None
try:
    print("connecting to {} at {}".format(args.dev, args.baud))
    stage = Stage(args.dev, baud=args.baud, feed=args.feed, z_feed=args.z_feed)
    print("connected")

    # ------------------------------------------------------------------ #
    def t_position():
        pos = stage.position
        print("  M114 parsed: {}".format(pos))
        if not isinstance(pos, Position):
            raise StageError("position is not a Position")
    check("read position", t_position)

    # ------------------------------------------------------------------ #
    def t_z_direction():
        """Establish that Z increases upward.

        Everything in the Z guard assumes "lower Z means closer to the target".
        If a machine is set up the other way round, the floor check protects
        the wrong side and the guards are worse than useless.
        """
        start = stage.sync()
        print("  Z now {:.3f}".format(start.z))
        confirm("raise Z by {} mm and watch which way the head goes?".format(Z_TEST))
        stage.move_to(z=start.z + Z_TEST, feed=args.z_feed, _override_floor=True)
        after = stage.sync()
        print("  Z now {:.3f} (commanded {:+.3f})".format(after.z, Z_TEST))
        if abs((after.z - start.z) - Z_TEST) > 0.01:
            raise StageError(
                "asked for {:+.3f}, moved {:+.3f} - the axis is not tracking"
                .format(Z_TEST, after.z - start.z))
        confirm("did the head move UP, away from the bed?")
        stage.move_to(z=start.z, feed=args.z_feed, _override_floor=True)
        print("  returned to {:.3f}".format(stage.sync().z))
    check("Z direction", t_z_direction)

    # ------------------------------------------------------------------ #
    def t_xy_accuracy():
        start = stage.sync()
        confirm("move {:+.1f} mm in X and {:+.1f} mm in Y?".format(XY_TEST, XY_TEST))
        stage.move_by(dx=XY_TEST, dy=XY_TEST)
        after = stage.sync()
        dx = after.x - start.x
        dy = after.y - start.y
        print("  commanded ({:+.3f}, {:+.3f}), measured ({:+.3f}, {:+.3f})".format(
            XY_TEST, XY_TEST, dx, dy))
        if abs(dx - XY_TEST) > 0.01 or abs(dy - XY_TEST) > 0.01:
            raise StageError("stage did not land where it was told")
        stage.move_to(start.x, start.y)
        print("  returned to ({:.3f}, {:.3f})".format(stage._pos.x, stage._pos.y))
    check("XY accuracy", t_xy_accuracy)

    # ------------------------------------------------------------------ #
    def t_cache_matches():
        """The cached position must agree with the stage.

        move_to computes absolute targets from the cache, so a cache that has
        drifted - because someone used the pendant, or a move was interrupted -
        turns every subsequent move into an offset error.
        """
        cached = stage._pos
        live = stage.position
        print("  cached {}".format(cached))
        print("  live   {}".format(live))
        if cached != live:
            raise StageError("cache and stage disagree - call sync()")
    check("cache consistency", t_cache_matches)

    # ------------------------------------------------------------------ #
    def t_z_floor():
        here = stage.sync().z
        stage.set_z_floor(clearance=0.0)
        print("  floor pinned at current Z {:.3f}".format(stage.z_floor))

        # Down: must be refused.
        try:
            stage.move_to(z=here - Z_TEST, feed=args.z_feed)
        except ZLimitError as e:
            print("  refused a move {:.1f} mm below the floor - correct".format(Z_TEST))
        else:
            raise StageError("moved below the floor - the guard is not working")

        # Up: must be allowed.
        stage.move_to(z=here + Z_TEST, feed=args.z_feed)
        print("  allowed a move {:.1f} mm above the floor - correct".format(Z_TEST))

        # lift(): always allowed.
        stage.lift(Z_TEST)
        print("  lift() reached {:.3f}".format(stage._pos.z))

        # lower() past the floor: refused.
        try:
            stage.lower(Z_TEST * 10)
        except ZLimitError:
            print("  lower() past the floor refused - correct")
        else:
            raise StageError("lower() went past the floor")

        stage.move_to(z=here + Z_TEST, feed=args.z_feed)
    check("Z floor", t_z_floor)

    # ------------------------------------------------------------------ #
    def t_home_guard():
        try:
            stage.home("XYZ")
        except ZLimitError:
            print("  home('XYZ') refused without force_z - correct")
        else:
            raise StageError("homed Z without force_z")
    check("home guard", t_home_guard)

    # ------------------------------------------------------------------ #
    def t_raster():
        """A small raster, checking the points land where they should."""
        step = 0.1
        origin = stage.sync()
        expected = stage.grid_size(0.2, 0.1, step)
        print("  {} points at {} mm pitch".format(expected, step))
        confirm("run it?")

        visited = []
        for pos in stage.raster(0.2, 0.1, step, origin=origin):
            visited.append((round(pos.x - origin.x, 3), round(pos.y - origin.y, 3)))

        print("  visited: {}".format(visited))
        if len(visited) != expected:
            raise StageError("expected {} points, got {}".format(
                expected, len(visited)))
        if len(set(visited)) != len(visited):
            raise StageError("a point was visited twice")
        # Row 1 must run backwards if serpentine is working.
        if visited[0][0] >= visited[2][0] or visited[3][0] <= visited[5][0]:
            raise StageError("serpentine did not reverse on the second row")
        print("  serpentine confirmed")

        stage.move_to(origin.x, origin.y)
        live = stage.position
        if abs(live.x - origin.x) > 0.01 or abs(live.y - origin.y) > 0.01:
            raise StageError("did not return to the origin")
        print("  returned to origin")
    check("raster", t_raster)

    # ------------------------------------------------------------------ #
    def t_resolution():
        """Sub-resolution steps must be rejected, not silently rounded."""
        try:
            stage.grid_size(1.0, 1.0, 0.0005)
        except ValueError:
            print("  0.0005 mm step rejected - correct")
        else:
            raise StageError("accepted a step finer than the resolution")
    check("resolution guard", t_resolution)

except KeyboardInterrupt:
    print("\ninterrupted")
except Exception as e:
    print("\nsetup failed: {}: {}".format(type(e).__name__, e))
finally:
    if stage is not None:
        try:
            stage.clear_z_floor()
            stage.close()
        except Exception:
            pass

    print("\n" + "=" * 50)
    for name in passed:
        print("  pass  {}".format(name))
    for name in failed:
        print("  FAIL  {}".format(name))
    print("{} passed, {} failed".format(len(passed), len(failed)))
    sys.exit(1 if failed else 0)

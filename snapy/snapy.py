"""
Snapmaker XYZ stage control for fault-injection work.

The stage speaks Marlin-style gcode over a serial port. This wraps it in
something that reads like positioning rather than string formatting, and keeps
the scan pattern out of the campaign loop:

    with Stage("/dev/snapy") as stage:
        for x, y in stage.raster(width=5, height=5, step=0.1):
            for delay in delays:
                fire(delay)

`raster` moves the head and yields the position it arrived at, so the campaign
loop only deals with campaign parameters.
"""
import csv
import time

import serial


class StageError(Exception):
    """Raised when the stage rejects a command or stops answering."""


class ZLimitError(StageError):
    """Raised when a move would take the head below the configured Z floor.

    The ferrite tip on an EMFI probe snaps on contact and is not cheap. Every
    move that touches Z is checked against the floor, and the floor has to be
    set deliberately - there is no sensible default for how close a given probe
    may come to a given board.
    """


class Position(object):
    """An X/Y/Z position in millimetres.

    Comparison and arithmetic are defined so callers can subtract positions to
    get a travel vector without unpacking dictionaries by hand.
    """

    __slots__ = ("x", "y", "z")

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __sub__(self, other):
        return Position(self.x - other.x, self.y - other.y, self.z - other.z)

    def __add__(self, other):
        return Position(self.x + other.x, self.y + other.y, self.z + other.z)

    def __eq__(self, other):
        return (abs(self.x - other.x) < 1e-6
                and abs(self.y - other.y) < 1e-6
                and abs(self.z - other.z) < 1e-6)

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def as_dict(self):
        return {"X": self.x, "Y": self.y, "Z": self.z}

    def __repr__(self):
        return "Position(x={:.3f}, y={:.3f}, z={:.3f})".format(self.x, self.y, self.z)


class Stage(object):
    """Serial control for a Marlin-style XYZ stage.

    Absolute mode (G90) is set once at connect and left alone; relative moves
    are expressed as absolute targets computed from the last known position.
    The original code toggled G91/G90 around every single move, which cost
    three round trips per step instead of one.
    """

    #: Feed rates the firmware is known to handle cleanly, mm/min.
    FEED_RATES = (3000, 1500, 500, 200)

    def __init__(self, dev="/dev/snapy", baud=115200, feed=500, timeout=3.5,
                 z_floor=None, z_feed=100, lift_on_exit=0.0):
        """
        :param dev: serial device
        :param feed: feed rate in mm/min; anything is accepted, but values
                     outside FEED_RATES have not been characterised
        :param timeout: serial read timeout; moves block until the firmware
                        answers `ok`, so this needs to exceed the longest move
        :param z_floor: lowest Z the head may reach, in machine coordinates.
                        Any move below it raises ZLimitError. None disables the
                        check, which is only reasonable with no probe fitted.
        :param z_feed: feed rate for Z moves. Deliberately slower than the XY
                       default: a probe descending at 500 mm/min gives no time
                       to react.
        :param lift_on_exit: mm to raise Z when leaving the context manager,
                             including on an exception. 0 disables it.
        """
        self.serial = serial.Serial(dev, baudrate=baud, timeout=timeout,
                                    write_timeout=timeout)
        self.feed = feed
        self.z_feed = z_feed
        self.z_floor = z_floor
        self.lift_on_exit = lift_on_exit
        self._pos = None
        time.sleep(0.2)
        self.serial.reset_input_buffer()
        self._command("G90")          # absolute positioning, set once
        self._command("G21")          # millimetres
        self._pos = self.position

    # ------------------------------------------------------------------ #
    # context manager
    # ------------------------------------------------------------------ #

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Lift before closing, exception or not. A campaign that dies with the
        # probe 200 um above a board leaves it there until someone notices.
        if self.lift_on_exit:
            try:
                self.move_by(dz=self.lift_on_exit, feed=self.z_feed,
                             _override_floor=True)
            except Exception as e:
                print("[!] could not lift Z on exit: {}".format(e))
        self.close()
        return False

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()

    # ------------------------------------------------------------------ #
    # transport
    # ------------------------------------------------------------------ #

    def _command(self, cmd, expect_ok=True):
        """Send one gcode line and wait for `ok`.

        Marlin answers every accepted command with `ok`; a timeout comes back
        as a short read, which is why the check is on the content rather than
        on an exception.
        """
        if isinstance(cmd, str):
            cmd = cmd.encode("ascii")
        self.serial.reset_input_buffer()
        self.serial.write(cmd + b"\n")
        reply = self.serial.read_until(b"ok")
        if expect_ok and b"ok" not in reply:
            raise StageError("no ok for {!r}, got {!r}".format(cmd, reply))
        return reply

    # ------------------------------------------------------------------ #
    # position
    # ------------------------------------------------------------------ #

    @property
    def position(self):
        """Read the live position with M114.

        M114 replies with something like
            X:10.00 Y:5.00 Z:0.00 E:0.00 Count X:800 Y:400 Z:0
        so the fields are picked out by name rather than by offset - the older
        code sliced the first three tokens, which breaks as soon as the
        firmware adds or reorders anything.
        """
        reply = self._command("M114").decode("ascii", "replace")
        coords = {}
        for token in reply.replace("\n", " ").split():
            if ":" not in token:
                continue
            key, _, value = token.partition(":")
            key = key.upper()
            if key in ("X", "Y", "Z") and key not in coords:
                try:
                    coords[key] = float(value)
                except ValueError:
                    pass
        missing = {"X", "Y", "Z"} - set(coords)
        if missing:
            raise StageError("M114 gave no {} in {!r}".format(
                ",".join(sorted(missing)), reply))
        return Position(coords["X"], coords["Y"], coords["Z"])

    def sync(self):
        """Re-read the stage and update the cached position."""
        self._pos = self.position
        return self._pos

    # ------------------------------------------------------------------ #
    # Z protection
    # ------------------------------------------------------------------ #

    def set_z_floor(self, z=None, clearance=0.0):
        """Set the lowest Z the head may reach.

        Called with no argument it takes the current position, which is the
        practical way to use it: jog down by hand until the probe is where you
        want it, then pin that as the limit.

        :param z: absolute Z, or None for "wherever the head is now"
        :param clearance: mm to add above z, for a margin against a board that
                          is not perfectly flat
        """
        if z is None:
            z = self.sync().z
        self.z_floor = z + clearance
        return self.z_floor

    def clear_z_floor(self):
        """Remove the limit. Only sensible with no probe fitted."""
        self.z_floor = None

    def _check_z(self, z):
        if self.z_floor is None:
            return
        # Half a resolution step of slack, so a move to exactly the floor is
        # allowed and floating point noise does not reject it.
        if z < self.z_floor - self.RESOLUTION / 2.0:
            raise ZLimitError(
                "Z {:.3f} is below the floor at {:.3f} - refusing to move. "
                "Use set_z_floor() to change it.".format(z, self.z_floor))

    def lift(self, mm, feed=None):
        """Raise Z by mm. Always permitted; moving away is never the risk."""
        return self.move_by(dz=abs(mm), feed=feed or self.z_feed,
                            _override_floor=True)

    def lower(self, mm, feed=None):
        """Lower Z by mm, subject to the floor."""
        return self.move_by(dz=-abs(mm), feed=feed or self.z_feed)

    def approach(self, target_z, step=0.05, feed=None, check=None):
        """Descend to target_z in steps, with an optional check between them.

        For finding the working height without trusting a single long move.
        `check` is called with the position after each step; returning True
        stops the descent there and returns that position.
        """
        self._check_z(target_z)
        if self._pos is None:
            self.sync()
        while self._pos.z > target_z + self.RESOLUTION / 2.0:
            next_z = max(target_z, self._pos.z - abs(step))
            self.move_to(z=next_z, feed=feed or self.z_feed)
            if check is not None and check(self._pos):
                return self._pos
        return self._pos

    # ------------------------------------------------------------------ #
    # movement
    # ------------------------------------------------------------------ #

    def move_to(self, x=None, y=None, z=None, feed=None, wait=True,
                _override_floor=False):
        """Move to an absolute position. Omitted axes keep their value.

        A move that would take Z below the floor raises ZLimitError before
        anything is sent to the stage.
        """
        if self._pos is None:
            self.sync()
        target = Position(
            self._pos.x if x is None else x,
            self._pos.y if y is None else y,
            self._pos.z if z is None else z,
        )
        # Downward moves are checked; upward ones and explicit lifts are not.
        if not _override_floor and target.z < self._pos.z:
            self._check_z(target.z)
        # Half a resolution step: anything smaller cannot move the stage, so
        # sending it would cost a round trip and change nothing.
        eps = self.RESOLUTION / 2.0
        parts = ["G0"]
        if abs(target.x - self._pos.x) >= eps:
            parts.append("X{:.3f}".format(target.x))
        if abs(target.y - self._pos.y) >= eps:
            parts.append("Y{:.3f}".format(target.y))
        if abs(target.z - self._pos.z) >= eps:
            parts.append("Z{:.3f}".format(target.z))
        if len(parts) == 1:
            return self._pos            # already there, nothing to send
        parts.append("F{}".format(int(feed or self.feed)))
        self._command(" ".join(parts))
        if wait:
            self.wait_for_moves()
        self._pos = target
        return target

    def move_by(self, dx=0.0, dy=0.0, dz=0.0, feed=None, wait=True,
                _override_floor=False):
        """Move relative to the current position.

        Implemented as an absolute move against the cached position so the
        firmware stays in G90 and one command goes out instead of three.
        """
        if self._pos is None:
            self.sync()
        return self.move_to(self._pos.x + dx, self._pos.y + dy, self._pos.z + dz,
                            feed=feed, wait=wait,
                            _override_floor=_override_floor)

    def wait_for_moves(self):
        """Block until the planner buffer drains (M400)."""
        self._command("M400")

    def home(self, axes="XY", force_z=False):
        """Home the given axes and resync the cached position.

        Z is excluded by default. Homing Z drives the head toward an endstop at
        whatever rate the firmware picks, ignoring the software floor entirely,
        and on a stage with a probe fitted that is how tips get broken. Pass
        force_z=True once you are sure nothing is in the way.
        """
        axes = axes.upper()
        if "Z" in axes and not force_z:
            raise ZLimitError(
                "homing Z ignores the software floor and can drive the probe "
                "into the target. Lift and clear the area first, then pass "
                "force_z=True.")
        self._command("G28 " + " ".join(axes))
        self.wait_for_moves()
        return self.sync()

    def set_origin(self):
        """Treat the current position as (0, 0, 0) via G92."""
        self._command("G92 X0 Y0 Z0")
        self._pos = Position(0.0, 0.0, 0.0)
        return self._pos

    # ------------------------------------------------------------------ #
    # scanning
    # ------------------------------------------------------------------ #

    #: Smallest movement the stage resolves, in mm.
    RESOLUTION = 0.001

    @classmethod
    def _to_um(cls, mm, what="value"):
        """Convert mm to integer micrometres, rejecting sub-resolution values.

        Grid arithmetic runs in micrometres rather than millimetres: repeated
        float addition over a few thousand points drifts by enough to push a
        coordinate across a rounding boundary, and the stage would silently
        snap it to a neighbouring step.
        """
        um = mm * 1000.0
        if abs(um - round(um)) > 1e-6:
            raise ValueError(
                "{} {} mm is finer than the {} mm resolution".format(
                    what, mm, cls.RESOLUTION))
        return int(round(um))

    def raster(self, width, height, step, serpentine=True, origin=None,
               feed=None, settle=0.0):
        """Walk a grid, yielding the position of each point.

        The head is already at the yielded position when control returns, so a
        campaign loop only has to deal with campaign parameters:

            for pos in stage.raster(5, 5, 0.1):
                for delay in delays:
                    fire(delay)

        :param width:  extent along X in mm
        :param height: extent along Y in mm
        :param step:   grid pitch in mm, a multiple of RESOLUTION
        :param serpentine: reverse X on alternate rows; halves travel and
                           avoids a long run back to the start of each row
        :param origin: grid corner; defaults to wherever the head is now
        :param settle: seconds to pause after each move, for a stage that
                       rings after a fast step
        """
        if step <= 0:
            raise ValueError("step must be positive")
        if origin is None:
            origin = self.sync()

        # Z is never touched by the scan; the head stays at whatever height it
        # was set to. Verify it is a height the floor allows, so a scan cannot
        # start from a position that was reached before the floor was set.
        self._check_z(self._pos.z if self._pos else self.sync().z)

        step_um = self._to_um(step, "step")
        nx = self._to_um(width, "width") // step_um + 1
        ny = self._to_um(height, "height") // step_um + 1
        ox_um = int(round(origin.x * 1000))
        oy_um = int(round(origin.y * 1000))

        for row in range(ny):
            xs = range(nx)
            if serpentine and row % 2:
                xs = reversed(range(nx))
            for col in xs:
                self.move_to((ox_um + col * step_um) / 1000.0,
                             (oy_um + row * step_um) / 1000.0,
                             feed=feed)
                if settle:
                    time.sleep(settle)
                yield self._pos

    def grid_size(self, width, height, step):
        """Number of points a raster of this shape will visit."""
        step_um = self._to_um(step, "step")
        nx = self._to_um(width, "width") // step_um + 1
        ny = self._to_um(height, "height") // step_um + 1
        return nx * ny


class ScanLog(object):
    """CSV log of positions and results.

    Kept separate from Stage so the stage can be used without leaving a file
    behind, and so the log can be closed properly. Use it as a context manager:

        with Stage(...) as stage, ScanLog("scan.csv") as log:
            for pos in stage.raster(5, 5, 0.1):
                log.record(pos, hit=run_attempt(), delay=delay)
    """

    def __init__(self, path="scan.csv", extra_fields=()):
        self.path = path
        self.fields = ["x", "y", "z", "hit"] + list(extra_fields)
        self._fh = open(path, "w", newline="")
        self._writer = csv.DictWriter(self._fh, fieldnames=self.fields,
                                      extrasaction="ignore")
        self._writer.writeheader()
        self.hits = 0
        self.rows = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Lift before closing, exception or not. A campaign that dies with the
        # probe 200 um above a board leaves it there until someone notices.
        if self.lift_on_exit:
            try:
                self.move_by(dz=self.lift_on_exit, feed=self.z_feed,
                             _override_floor=True)
            except Exception as e:
                print("[!] could not lift Z on exit: {}".format(e))
        self.close()
        return False

    def record(self, pos, hit=False, **extra):
        row = {"x": pos.x, "y": pos.y, "z": pos.z, "hit": int(bool(hit))}
        row.update(extra)
        self._writer.writerow(row)
        self._fh.flush()          # campaigns get killed; do not lose the log
        self.rows += 1
        if hit:
            self.hits += 1

    def close(self):
        if self._fh and not self._fh.closed:
            self._fh.close()


# Backwards-compatible alias for existing scripts.
Snapy = Stage

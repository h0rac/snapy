"""
Shared stage configuration.

The Stage tab of the web UI writes the working height and scan origin
here; campaign scripts read them back. Keeping it in one place means the Z floor set up by hand is the
same one the campaign runs under, rather than a number retyped from memory.

    from snapy.config import StageConfig

    cfg = StageConfig.load()
    with cfg.open_stage(lift_on_exit=5.0) as stage:
        stage.goto_origin()
        for pos in stage.raster(5, 5, 0.1):
            ...
"""
import json
import os

from .snapy import Stage, Position

DEFAULT_PATH = os.path.expanduser("~/.snapy-stage.json")


class StageConfig(object):
    """Origin and Z floor, persisted between sessions."""

    def __init__(self, path=DEFAULT_PATH, origin=None, z_floor=None,
                 dev="/dev/snapy", feed=500, z_feed=100):
        self.path = path
        self.origin = origin
        self.z_floor = z_floor
        self.dev = dev
        self.feed = feed
        self.z_feed = z_feed

    @classmethod
    def load(cls, path=DEFAULT_PATH, require_floor=True):
        """Read the config written by the jog panel.

        :param require_floor: refuse to load without a Z floor. A campaign that
                              starts with no floor set can drive the probe into
                              the board on the first move, so the default is to
                              treat a missing floor as a setup error rather
                              than something to warn about and continue past.
        """
        if not os.path.exists(path):
            raise IOError(
                "no stage config at {} - set the floor in the Stage tab of the "
                "web UI first".format(path))
        with open(path) as fh:
            data = json.load(fh)

        origin = None
        if data.get("origin"):
            o = data["origin"]
            origin = Position(o["x"], o["y"], o.get("z", 0.0))

        z_floor = data.get("z_floor")
        if require_floor and z_floor is None:
            raise ValueError(
                "{} has no z_floor - press Set floor in the Stage tab of the "
                "web UI before running a campaign".format(path))

        return cls(path=path, origin=origin, z_floor=z_floor,
                   dev=data.get("dev", "/dev/snapy"),
                   feed=data.get("feed", 500),
                   z_feed=data.get("z_feed", 100))

    def save(self):
        data = {"z_floor": self.z_floor, "dev": self.dev,
                "feed": self.feed, "z_feed": self.z_feed}
        if self.origin is not None:
            data["origin"] = {"x": self.origin.x, "y": self.origin.y,
                              "z": self.origin.z}
        with open(self.path, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")

    def open_stage(self, **kwargs):
        """Open the stage with the saved floor already applied.

        Any keyword overrides the stored value, so a campaign can raise
        lift_on_exit without editing the config.
        """
        params = {"dev": self.dev, "feed": self.feed, "z_feed": self.z_feed,
                  "z_floor": self.z_floor}
        params.update(kwargs)
        dev = params.pop("dev")
        return _ConfiguredStage(self, dev, **params)

    def __repr__(self):
        return "StageConfig(origin={}, z_floor={})".format(self.origin, self.z_floor)


class _ConfiguredStage(Stage):
    """A Stage that knows the saved origin."""

    def __init__(self, config, dev, **kwargs):
        Stage.__init__(self, dev, **kwargs)
        self.config = config

    def goto_origin(self, feed=None):
        """Move to the saved origin, XY before Z.

        Doing XY first means a saved Z below the current height cannot drag the
        probe sideways at working distance on the way there.
        """
        if self.config.origin is None:
            raise ValueError("no origin saved - click a cell on the scan map "
                             "in the web UI to set one")
        o = self.config.origin
        self.move_to(o.x, o.y, feed=feed)
        self.move_to(z=o.z, feed=feed or self.z_feed)
        return self._pos

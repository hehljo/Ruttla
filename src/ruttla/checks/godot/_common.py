"""Shared Godot source selection; no rules registered here."""

from ruttla.core import Context

PLATFORM = "godot"


def _gd(ctx: Context):
    return ctx.files(".gd")

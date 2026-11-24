"""Granular IR patcher for document artifacts (replace_block, insert_block, delete_block)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class InvalidPatchError(Exception):
    """Raised when an IR patch operation is malformed or targets a missing block."""


def apply_ir_patch(source: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply one IR patch operation and return a new source dict."""
    op = patch.get("op")
    updated = deepcopy(source)
    blocks = updated.get("blocks")
    if not isinstance(blocks, list):
        raise InvalidPatchError("Artifact source does not contain a 'blocks' list.")

    if op == "replace_block":
        block_id = patch.get("block_id")
        new_block = patch.get("block")
        if not isinstance(new_block, dict):
            raise InvalidPatchError("replace_block requires a 'block' object.")
        for idx, blk in enumerate(blocks):
            if isinstance(blk, dict) and blk.get("id") == block_id:
                blocks[idx] = new_block
                return updated
        raise InvalidPatchError(f"Block '{block_id}' not found.")

    if op == "insert_block":
        new_block = patch.get("block")
        if not isinstance(new_block, dict):
            raise InvalidPatchError("insert_block requires a 'block' object.")
        after_id = patch.get("after_block_id")
        if not after_id:
            blocks.append(new_block)
            return updated
        for idx, blk in enumerate(blocks):
            if isinstance(blk, dict) and blk.get("id") == after_id:
                blocks.insert(idx + 1, new_block)
                return updated
        raise InvalidPatchError(f"after_block_id '{after_id}' not found.")

    if op == "delete_block":
        block_id = patch.get("block_id")
        new_blocks = [b for b in blocks if not (isinstance(b, dict) and b.get("id") == block_id)]
        if len(new_blocks) == len(blocks):
            raise InvalidPatchError(f"Block '{block_id}' not found.")
        updated["blocks"] = new_blocks
        return updated

    raise InvalidPatchError(f"Unsupported patch op: {op}")

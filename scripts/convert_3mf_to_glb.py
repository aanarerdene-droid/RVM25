#!/usr/bin/env python3
"""Convert this project's simple 3MF base-material meshes into a compact GLB."""
from __future__ import annotations

import json
import math
import struct
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "RVM25_reverse_vending_machine_color.3mf"
DEST = ROOT / "assets" / "rvm-machine.glb"
NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}


def align4(data: bytearray) -> None:
    while len(data) % 4:
        data.append(0)


def float_bytes(values: list[float]) -> bytes:
    return struct.pack("<" + "f" * len(values), *values)


def uint_bytes(values: list[int]) -> bytes:
    return struct.pack("<" + "H" * len(values), *values)


def parse_hex_color(value: str) -> list[float]:
    value = value.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    alpha = int(value[6:8], 16) / 255 if len(value) == 8 else 1.0
    return channels + [alpha]


def main() -> None:
    with zipfile.ZipFile(SOURCE) as archive:
        root = ET.fromstring(archive.read("3D/3dmodel.model"))

    resources = root.find("m:resources", NS)
    base_materials = resources.find("m:basematerials", NS)
    color_defs = [parse_hex_color(x.attrib["displaycolor"]) for x in base_materials]
    material_names = [x.attrib.get("name", f"Material {i + 1}") for i, x in enumerate(base_materials)]
    objects = [x for x in resources.findall("m:object", NS) if x.find("m:mesh", NS) is not None]
    binary = bytearray()
    views = []
    accessors = []
    meshes = []
    materials = []
    nodes = []

    def add_view(payload: bytes, target: int) -> int:
        align4(binary)
        offset = len(binary)
        binary.extend(payload)
        view_index = len(views)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(payload), "target": target})
        return view_index

    for material_index, obj in enumerate(objects):
        mesh = obj.find("m:mesh", NS)
        vertices = [
            (float(v.attrib["x"]), float(v.attrib["y"]), float(v.attrib["z"]))
            for v in mesh.find("m:vertices", NS)
        ]
        triangles = [
            (int(t.attrib["v1"]), int(t.attrib["v2"]), int(t.attrib["v3"]))
            for t in mesh.find("m:triangles", NS)
        ]
        normals = [[0.0, 0.0, 0.0] for _ in vertices]
        for a, b, c in triangles:
            p, q, r = vertices[a], vertices[b], vertices[c]
            u = (q[0] - p[0], q[1] - p[1], q[2] - p[2])
            v = (r[0] - p[0], r[1] - p[1], r[2] - p[2])
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            for i in (a, b, c):
                normals[i][0] += n[0]
                normals[i][1] += n[1]
                normals[i][2] += n[2]
        flat_normals = []
        for n in normals:
            length = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1
            flat_normals.extend((n[0] / length, n[1] / length, n[2] / length))

        flat_positions = [coord for vertex in vertices for coord in vertex]
        indices = [i for tri in triangles for i in tri]
        pos_view = add_view(float_bytes(flat_positions), 34962)
        normal_view = add_view(float_bytes(flat_normals), 34962)
        index_view = add_view(uint_bytes(indices), 34963)
        low = [min(v[i] for v in vertices) / 1000 for i in range(3)]
        high = [max(v[i] for v in vertices) / 1000 for i in range(3)]
        pos_accessor = len(accessors)
        accessors.append({"bufferView": pos_view, "componentType": 5126, "count": len(vertices), "type": "VEC3", "min": low, "max": high})
        normal_accessor = len(accessors)
        accessors.append({"bufferView": normal_view, "componentType": 5126, "count": len(vertices), "type": "VEC3"})
        index_accessor = len(accessors)
        accessors.append({"bufferView": index_view, "componentType": 5123, "count": len(indices), "type": "SCALAR", "min": [min(indices)], "max": [max(indices)]})

        color = color_defs[int(obj.attrib.get("pindex", "0"))]
        material_out_index = len(materials)
        materials.append({
            "name": material_names[int(obj.attrib.get("pindex", "0"))],
            "pbrMetallicRoughness": {"baseColorFactor": color, "metallicFactor": 0.05, "roughnessFactor": 0.52},
            "doubleSided": True,
        })
        meshes.append({"name": obj.attrib.get("name", "RVM part"), "primitives": [{"attributes": {"POSITION": pos_accessor, "NORMAL": normal_accessor}, "indices": index_accessor, "material": material_out_index, "mode": 4}]})
        nodes.append({"name": obj.attrib.get("name", "RVM part"), "mesh": len(meshes) - 1})

    align4(binary)
    gltf = {
        "asset": {"version": "2.0", "generator": "Loopwise 3MF color mesh converter"},
        "scene": 0,
        # Node 0 is the parent transform; the part meshes start at node 1.
        # Pointing the scene at len(nodes) made only the final 3MF part
        # (the QR panel) visible in viewers.
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "RVM25 · millimeter to meter · Z-up to Y-up", "rotation": [-0.70710678, 0, 0, 0.70710678], "scale": [0.001, 0.001, 0.001], "children": list(range(1, len(nodes) + 1))}] + nodes,
        "meshes": meshes,
        "materials": materials,
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    json_chunk = bytearray(json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    while len(json_chunk) % 4:
        json_chunk.append(0x20)
    while len(binary) % 4:
        binary.append(0)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(binary)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with DEST.open("wb") as output:
        output.write(struct.pack("<4sII", b"glTF", 2, total_length))
        output.write(struct.pack("<I4s", len(json_chunk), b"JSON"))
        output.write(json_chunk)
        output.write(struct.pack("<I4s", len(binary), b"BIN\x00"))
        output.write(binary)
    print(f"Wrote {DEST} ({DEST.stat().st_size:,} bytes) with {len(meshes)} colored meshes")


if __name__ == "__main__":
    main()

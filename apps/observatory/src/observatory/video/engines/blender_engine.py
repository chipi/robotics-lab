"""The Blender engine of the video export (ADR-0017): a job to a video, rendered by Blender (EEVEE), the robot built from its
description (RFC-0011: its URDF's links and meshes) and moved by our own forward kinematics (observatory.kinematics, the one
checked against MuJoCo). Run by Blender itself:

    blender --background --factory-startup --python blender_engine.py -- job.json

The job is the same as the MuJoCo engine's, with the robot's `urdf` (an absolute path). The room is the scene's boxes and
drops (world frame) or the robot's own map (map frame), as there. Each link is an empty with its meshes as children; per
frame the empties take the link poses; the camera follows the trunk from behind and above.
"""

import json
import math
import sys
from pathlib import Path

import bpy  # noqa: E402  (Blender's own module)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))           # apps/observatory/src: observatory.kinematics is plain Python, Blender's can import it
from observatory import kinematics as kin  # noqa: E402


def material(name: str, rgba: list):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = rgba
    if rgba[3] < 1.0:
        bsdf.inputs["Alpha"].default_value = rgba[3]
        m.blend_method = "BLEND" if hasattr(m, "blend_method") else None
    return m


def box(name: str, cx, cy, hx, hy, z0, z1, yaw, mat):
    bpy.ops.mesh.primitive_cube_add(size=2, location=(cx, cy, (z0 + z1) / 2), rotation=(0, 0, yaw))
    o = bpy.context.active_object
    o.name = name
    o.scale = (hx, hy, max((z1 - z0) / 2, 0.0005))
    o.data.materials.append(mat)
    return o


def import_stl(path: Path):
    before = set(bpy.data.objects)
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=str(path))
    else:
        bpy.ops.import_mesh.stl(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    return new[0] if new else None


def quat_blender(q):
    return (q[0], q[1], q[2], q[3])                  # Blender's quaternions are (w, x, y, z), as ours


def main() -> None:
    job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    tr, rb = job["track"], job["robot"]
    rob = kin.load(Path(rb["urdf"]))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    w, h = job["size"]
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.fps = int(round(tr["fps"]))
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
    if hasattr(scene.render.image_settings, "media_type"):          # Blender 5: a video is a media type, then its format
        scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.filepath = job["out"]
    scene.frame_start, scene.frame_end = 1, len(tr["frames"])

    # the room
    floor = material("floor", [0.32, 0.40, 0.50, 1.0])
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
    bpy.context.active_object.data.materials.append(floor)
    walls, drop, cell = material("walls", [0.78, 0.78, 0.80, 0.45]), material("drop", [0.30, 0.10, 0.32, 1.0]), material("map", [0.55, 0.45, 0.35, 1.0])
    if tr.get("frame") == "map" and tr.get("map"):
        g = tr["map"]
        for k, c in enumerate(g["cells"]):
            if c == "#":
                r, col = divmod(k, g["w"])
                box(f"map{k}", g["origin"][0] + (col + 0.5) * g["res"], g["origin"][1] + (r + 0.5) * g["res"], g["res"] / 2, g["res"] / 2, 0, 0.12, 0, cell)
    else:
        for i, b in enumerate(job["scene"].get("boxes", [])):
            box(f"b{i}", b["cx"], b["cy"], b["hx"], b["hy"], b["z0"], b["z1"], b.get("yaw", 0.0), walls)
        for i, hz in enumerate(job["scene"].get("hazards", [])):
            box(f"h{i}", (hz["x0"] + hz["x1"]) / 2, (hz["y0"] + hz["y1"]) / 2, (hz["x1"] - hz["x0"]) / 2, (hz["y1"] - hz["y0"]) / 2,
                0.0005, 0.0015, hz.get("yaw", 0.0), drop)

    # the robot: an empty per link, its meshes as children at their pose in the link
    empties = {}
    for link, visuals in rob.links.items():
        e = bpy.data.objects.new(link, None)
        e.rotation_mode = "QUATERNION"
        scene.collection.objects.link(e)
        empties[link] = e
        for i, v in enumerate(visuals):
            o = import_stl(rob.folder / v.mesh)
            if o is None:
                continue
            o.name = f"{link}.{i}"
            o.parent = e
            o.rotation_mode = "QUATERNION"
            o.location = v.origin[0]
            o.rotation_quaternion = quat_blender(v.origin[1])
            o.data.materials.append(material(f"{link}.{i}", v.rgba))

    # light and camera
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 5))
    bpy.context.active_object.data.energy = 3.0
    bpy.ops.object.camera_add()
    cam = bpy.context.active_object
    scene.camera = cam
    cam.data.lens = 35

    look, heading = None, None
    for k, f in enumerate(tr["frames"], start=1):
        poses = rob.link_poses(f["joints"], (f["pos"], f["quat"]))
        for link, (p, q) in poses.items():
            e = empties[link]
            e.location = p
            e.rotation_quaternion = quat_blender(q)
            e.keyframe_insert("location", frame=k)
            e.keyframe_insert("rotation_quaternion", frame=k)
        wq, xq, yq, zq = f["quat"]
        yaw = math.atan2(2 * (wq * zq + xq * yq), 1 - 2 * (yq * yq + zq * zq))
        heading = yaw if heading is None else heading + 0.05 * math.atan2(math.sin(yaw - heading), math.cos(yaw - heading))
        tx, ty = f["pos"][0], f["pos"][1]
        look = (tx, ty) if look is None else (look[0] + 0.15 * (tx - look[0]), look[1] + 0.15 * (ty - look[1]))
        back = heading + math.pi - 0.5
        cam.location = (look[0] + 1.0 * math.cos(back), look[1] + 1.0 * math.sin(back), 0.85)
        dx, dy, dz = look[0] - cam.location[0], look[1] - cam.location[1], 0.08 - cam.location[2]
        cam.rotation_mode = "XYZ"
        cam.rotation_euler = (math.atan2(math.hypot(dx, dy), -dz), 0.0, math.atan2(dy, dx) - math.pi / 2)
        cam.keyframe_insert("location", frame=k)
        cam.keyframe_insert("rotation_euler", frame=k)
    bpy.ops.render.render(animation=True)
    print(f"video {job['out']}: {len(tr['frames'])} frames at {tr['fps']:g} fps, {w}x{h}, Blender, pose from the {tr.get('source', 'truth')}",
          flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate professional CAD-style floor plan SVGs for ITA River Loft Room."""

import math

# === Constants ===
SCALE = 72  # 1m = 72px
OX = 140    # origin X offset (px)
OY = 150    # origin Y offset (px)
CW = 1400   # canvas width
CH = 980    # canvas height

# Colors
C_BG = "#FFFFFF"
C_OUTER_WALL = "#111827"
C_INNER_WALL = "#1E293B"
C_DOOR = "#334155"
C_WINDOW = "#475569"
C_FURNITURE = "#64748B"
C_FURNITURE_FILL = "#F8FAFC"
C_DIM = "#64748B"
C_DIM_TEXT = "#334155"
C_ROOM_NAME = "#111827"
C_AREA = "#475569"
C_VOID_FILL = "#F1F5F9"
C_VOID_LINE = "#94A3B8"
C_STAIR = "#64748B"
C_RAILING = "#475569"
C_REF_OUTLINE = "#94A3B8"

# Wall thickness (px)
W_OUTER = 6
W_INNER = 3
W_DOOR_LEAF = 2
W_DOOR_ARC = 1.5
W_WINDOW = 1
W_FURNITURE = 1
W_DIM = 0.8
W_RAILING = 1.5

def mx(m):
    return OX + m * SCALE

def my(m):
    return OY + m * SCALE

def wall_line(x1, y1, x2, y2, outer=False):
    w = W_OUTER if outer else W_INNER
    c = C_OUTER_WALL if outer else C_INNER_WALL
    return f'<line x1="{mx(x1):.1f}" y1="{my(y1):.1f}" x2="{mx(x2):.1f}" y2="{my(y2):.1f}" stroke="{c}" stroke-width="{w}" stroke-linecap="square"/>'

def window_line(x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return ""
    nx = -dy / length
    ny = dx / length
    offsets = [-0.06, -0.02, 0.02, 0.06]
    lines = []
    for off in offsets:
        ox_ = nx * off
        oy_ = ny * off
        lines.append(
            f'<line x1="{mx(x1+ox_):.1f}" y1="{my(y1+oy_):.1f}" x2="{mx(x2+ox_):.1f}" y2="{my(y2+oy_):.1f}" '
            f'stroke="{C_WINDOW}" stroke-width="{W_WINDOW}" stroke-linecap="square"/>'
        )
    return "\n".join(lines)

def door_swing(hinge_m, closed_end_m, open_end_m, width_m):
    hx, hy = hinge_m
    cx, cy = closed_end_m
    ox_, oy = open_end_m
    r = width_m * SCALE
    leaf = f'<line x1="{mx(hx):.1f}" y1="{my(hy):.1f}" x2="{mx(cx):.1f}" y2="{my(cy):.1f}" stroke="{C_DOOR}" stroke-width="{W_DOOR_LEAF}" stroke-linecap="round"/>'
    vcx = cx - hx
    vcy = cy - hy
    vox = ox_ - hx
    voy = oy - hy
    cross = vcx * voy - vcy * vox
    sweep = 1 if cross > 0 else 0
    arc = f'<path d="M {mx(cx):.1f} {my(cy):.1f} A {r:.1f} {r:.1f} 0 0 {sweep} {mx(ox_):.1f} {my(oy):.1f}" fill="none" stroke="{C_DOOR}" stroke-width="{W_DOOR_ARC}"/>'
    return leaf + "\n" + arc

def sliding_door(x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return ""
    ux = dx / length
    uy = dy / length
    nx = -uy
    ny = ux
    track_off = 0.04
    t1 = f'<line x1="{mx(x1+nx*track_off):.1f}" y1="{my(y1+ny*track_off):.1f}" x2="{mx(x2+nx*track_off):.1f}" y2="{my(y2+ny*track_off):.1f}" stroke="{C_DOOR}" stroke-width="0.8"/>'
    t2 = f'<line x1="{mx(x1-nx*track_off):.1f}" y1="{my(y1-ny*track_off):.1f}" x2="{mx(x2-nx*track_off):.1f}" y2="{my(y2-ny*track_off):.1f}" stroke="{C_DOOR}" stroke-width="0.8"/>'
    panel_off = 0.025
    panel_len = length * 0.6
    p1s_x = x1 + ux * length * 0.05 + nx * panel_off
    p1s_y = y1 + uy * length * 0.05 + ny * panel_off
    p1e_x = x1 + ux * (length * 0.05 + panel_len) + nx * panel_off
    p1e_y = y1 + uy * (length * 0.05 + panel_len) + ny * panel_off
    p2s_x = x1 + ux * length * 0.35 - nx * panel_off
    p2s_y = y1 + uy * length * 0.35 - ny * panel_off
    p2e_x = x1 + ux * (length * 0.35 + panel_len) - nx * panel_off
    p2e_y = y1 + uy * (length * 0.35 + panel_len) - ny * panel_off
    pw = 3
    p1 = f'<line x1="{mx(p1s_x):.1f}" y1="{my(p1s_y):.1f}" x2="{mx(p1e_x):.1f}" y2="{my(p1e_y):.1f}" stroke="{C_DOOR}" stroke-width="{pw}" stroke-linecap="round" opacity="0.8"/>'
    p2 = f'<line x1="{mx(p2s_x):.1f}" y1="{my(p2s_y):.1f}" x2="{mx(p2e_x):.1f}" y2="{my(p2e_y):.1f}" stroke="{C_DOOR}" stroke-width="{pw}" stroke-linecap="round" opacity="0.8"/>'
    return "\n".join([t1, t2, p1, p2])

def rect_m(x, y, w, h, fill=C_FURNITURE_FILL, stroke=C_FURNITURE, sw=W_FURNITURE, extra=""):
    return f'<rect x="{mx(x):.1f}" y="{my(y):.1f}" width="{w*SCALE:.1f}" height="{h*SCALE:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" {extra}/>'

def circle_m(cx, cy, r, fill=C_FURNITURE_FILL, stroke=C_FURNITURE, sw=W_FURNITURE):
    return f'<circle cx="{mx(cx):.1f}" cy="{my(cy):.1f}" r="{r*SCALE:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'

def line_m(x1, y1, x2, y2, stroke=C_FURNITURE, sw=W_FURNITURE, extra=""):
    return f'<line x1="{mx(x1):.1f}" y1="{my(y1):.1f}" x2="{mx(x2):.1f}" y2="{my(y2):.1f}" stroke="{stroke}" stroke-width="{sw}" {extra}/>'

def text_m(x, y, text, size=12, color="#111827", weight="normal", anchor="middle", extra=""):
    return f'<text x="{mx(x):.1f}" y="{my(y):.1f}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}" font-family="\'PingFang SC\',\'Microsoft YaHei\',\'Helvetica Neue\',sans-serif" {extra}>{text}</text>'

def room_label(cx, cy, name, area, name_size=18):
    name_t = text_m(cx, cy, name, size=name_size, color=C_ROOM_NAME, weight="700")
    area_t = text_m(cx, cy + 0.35, f"{area:.1f}㎡", size=12, color=C_AREA, weight="400")
    return name_t + "\n" + area_t

def dim_line_h(y_m, x1_m, x2_m, label, side="south", offset_m=0.0):
    if side == "south":
        sign = 1
    else:
        sign = -1
    y_dim = y_m + sign * offset_m
    x1_px = mx(x1_m)
    x2_px = mx(x2_m)
    y_px = my(y_dim)
    ext1 = f'<line x1="{x1_px:.1f}" y1="{my(y_m):.1f}" x2="{x1_px:.1f}" y2="{y_px + sign*5:.1f}" stroke="{C_DIM}" stroke-width="{W_DIM}"/>'
    ext2 = f'<line x1="{x2_px:.1f}" y1="{my(y_m):.1f}" x2="{x2_px:.1f}" y2="{y_px + sign*5:.1f}" stroke="{C_DIM}" stroke-width="{W_DIM}"/>'
    main = f'<line x1="{x1_px:.1f}" y1="{y_px:.1f}" x2="{x2_px:.1f}" y2="{y_px:.1f}" stroke="{C_DIM}" stroke-width="{W_DIM}"/>'
    tick_len = 5
    t1 = f'<line x1="{x1_px-tick_len:.1f}" y1="{y_px-tick_len:.1f}" x2="{x1_px+tick_len:.1f}" y2="{y_px+tick_len:.1f}" stroke="{C_DIM}" stroke-width="{W_DIM}"/>'
    t2 = f'<line x1="{x2_px-tick_len:.1f}" y1="{y_px-tick_len:.1f}" x2="{x2_px+tick_len:.1f}" y2="{y_px+tick_len:.1f}" stroke="{C_DIM}" stroke-width="{W_DIM}"/>'
    label_y = y_px + sign * 14 if side == "south" else y_px - 5
    label_t = f'<text x="{(x1_px+x2_px)/2:.1f}" y="{label_y:.1f}" font-size="11" fill="{C_DIM_TEXT}" text-anchor="middle" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">{label}</text>'
    return "\n".join([ext1, ext2, main, t1, t2, label_t])

def dim_line_v(x_m, y1_m, y2_m, label, side="east", offset_m=0.0):
    if side == "east":
        sign = 1
    else:
        sign = -1
    x_dim = x_m + sign * offset_m
    x1_px = mx(x_dim)
    y1_px = my(y1_m)
    y2_px = my(y2_m)
    x_wall_px = mx(x_m)
    ext1 = f'<line x1="{x_wall_px:.1f}" y1="{y1_px:.1f}" x2="{x1_px + sign*5:.1f}" y2="{y1_px:.1f}" stroke="{C_DIM}" stroke-width="{W_DIM}"/>'
    ext2 = f'<line x1="{x_wall_px:.1f}" y1="{y2_px:.1f}" x2="{x1_px + sign*5:.1f}" y2="{y2_px:.1f}" stroke="{C_DIM}" stroke-width="{W_DIM}"/>'
    main = f'<line x1="{x1_px:.1f}" y1="{y1_px:.1f}" x2="{x1_px:.1f}" y2="{y2_px:.1f}" stroke="{C_DIM}" stroke-width="{W_DIM}"/>'
    tick_len = 5
    t1 = f'<line x1="{x1_px-tick_len:.1f}" y1="{y1_px-tick_len:.1f}" x2="{x1_px+tick_len:.1f}" y2="{y1_px+tick_len:.1f}" stroke="{C_DIM}" stroke-width="{W_DIM}"/>'
    t2 = f'<line x1="{x1_px-tick_len:.1f}" y1="{y2_px-tick_len:.1f}" x2="{x1_px+tick_len:.1f}" y2="{y2_px+tick_len:.1f}" stroke="{C_DIM}" stroke-width="{W_DIM}"/>'
    cy_t = (y1_px + y2_px) / 2
    if side == "east":
        label_t = f'<text x="{x1_px + 14:.1f}" y="{cy_t:.1f}" font-size="11" fill="{C_DIM_TEXT}" text-anchor="middle" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif" transform="rotate(-90,{x1_px + 14:.1f},{cy_t:.1f})">{label}</text>'
    else:
        label_t = f'<text x="{x1_px - 14:.1f}" y="{cy_t:.1f}" font-size="11" fill="{C_DIM_TEXT}" text-anchor="middle" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif" transform="rotate(-90,{x1_px - 14:.1f},{cy_t:.1f})">{label}</text>'
    return "\n".join([ext1, ext2, main, t1, t2, label_t])


# ============================================================
# LEVEL 1
# ============================================================
def gen_level1():
    parts = []
    parts.append(f'<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{CW}" height="{CH}" viewBox="0 0 {CW} {CH}" style="background:{C_BG};">')
    parts.append('<defs>')
    parts.append('<pattern id="hatchL1" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">')
    parts.append(f'<line x1="0" y1="0" x2="0" y2="6" stroke="{C_VOID_LINE}" stroke-width="0.6"/>')
    parts.append('</pattern>')
    parts.append(f'<marker id="arrowUpL1" markerWidth="12" markerHeight="12" refX="6" refY="6" orient="auto">')
    parts.append(f'<path d="M0,12 L6,0 L12,12 Z" fill="{C_ROOM_NAME}"/>')
    parts.append('</marker>')
    parts.append('</defs>')

    # Title
    parts.append(f'<text x="{CW/2}" y="32" font-size="20" fill="{C_ROOM_NAME}" text-anchor="middle" font-weight="700" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">一层平面图 · 公共生活层</text>')
    parts.append(f'<text x="{CW/2}" y="52" font-size="11" fill="{C_AREA}" text-anchor="middle" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">比例 1:72 · 单位：米（m）· 层高 5.15m · 二层楼板标高 2.85m · 约 80㎡</text>')

    # FOOTPRINT FILL
    l1_verts = [(0,0),(4.2,0),(4.2,-0.6),(11.2,-0.6),(11.2,1.2),(12.8,1.2),(12.8,10.0),(1.6,10.0),(1.6,9.0),(0,9.0)]
    pts_str = " ".join(f"{mx(v[0]):.1f},{my(v[1]):.1f}" for v in l1_verts)
    parts.append(f'<polygon points="{pts_str}" fill="{C_BG}" stroke="none"/>')

    # OUTER WALLS
    parts.append(wall_line(0, 0, 4.2, 0, outer=True))
    parts.append(wall_line(4.2, 0, 4.2, -0.6, outer=True))
    # North projection with window gaps
    parts.append(wall_line(4.2, -0.6, 4.0, -0.6, outer=True))
    # kitchen window 4.0~7.2
    parts.append(wall_line(7.2, -0.6, 10.0, -0.6, outer=True))
    # bath window 10.0~11.2
    parts.append(wall_line(11.2, -0.6, 11.2, 1.2, outer=True))
    parts.append(wall_line(11.2, 1.2, 12.8, 1.2, outer=True))
    parts.append(wall_line(12.8, 1.2, 12.8, 8.0, outer=True))
    # balcony east 8.0~10.0 is window
    # South wall with window gaps
    # main window 1.6~10.2
    parts.append(wall_line(10.2, 10.0, 12.8, 10.0, outer=True))
    parts.append(wall_line(1.6, 10.0, 1.6, 9.0, outer=True))
    parts.append(wall_line(1.6, 9.0, 0, 9.0, outer=True))
    # West wall with entry door
    parts.append(wall_line(0, 9.0, 0, 2.325, outer=True))
    # door gap 1.275~2.325
    parts.append(wall_line(0, 1.275, 0, 0, outer=True))
    # West wall of balcony (X=9.8 from Y=8.0 to 10.0) - with sliding door opening
    parts.append(wall_line(9.8, 8.0, 9.8, 8.2, outer=True))
    # slider opening 8.2~9.8
    parts.append(wall_line(9.8, 9.8, 9.8, 10.0, outer=True))
    # North wall of balcony (Y=8.0 from X=9.8 to 12.8) - with sliding door
    parts.append(wall_line(9.8, 8.0, 10.0, 8.0, outer=True))
    # slider opening 10.0~12.4
    parts.append(wall_line(12.4, 8.0, 12.8, 8.0, outer=True))

    # WINDOWS
    parts.append(window_line(4.0, -0.6, 7.2, -0.6))
    parts.append(window_line(10.0, -0.6, 11.2, -0.6))
    parts.append(window_line(1.6, 10.0, 10.2, 10.0))
    parts.append(window_line(9.8, 10.0, 12.8, 10.0))
    parts.append(window_line(12.8, 8.0, 12.8, 10.0))

    # INNER WALLS
    parts.append(wall_line(1.2, 0, 1.2, 1.2))
    parts.append(wall_line(1.2, 3.6, 1.2, 6.4))
    parts.append(wall_line(2.4, 0, 2.4, 1.2))
    parts.append(wall_line(1.2, 3.6, 2.4, 3.6))
    parts.append(wall_line(7.2, 0, 7.2, -0.6))
    parts.append(wall_line(7.2, 0, 7.2, 3.2))
    parts.append(wall_line(7.2, 2.6, 10.0, 2.6))
    # bath door gap 10.0~10.8
    parts.append(wall_line(10.8, 2.6, 11.2, 2.6))
    parts.append(wall_line(11.2, 1.2, 11.2, 2.6))
    # Bath shower glass
    parts.append(line_m(10.2, 1.5, 11.2, 1.5, stroke=C_FURNITURE, sw=1, extra='stroke-dasharray="4,2"'))
    parts.append(line_m(10.2, 1.5, 10.2, 2.6, stroke=C_FURNITURE, sw=1, extra='stroke-dasharray="4,2"'))

    # DOORS
    parts.append(door_swing((0, 1.275), (0, 2.325), (1.05, 1.275), 1.05))
    parts.append(door_swing((10.8, 2.6), (10.0, 2.6), (10.8, 1.8), 0.8))
    parts.append(sliding_door(10.0, 8.0, 12.4, 8.0))

    # STAIRS
    parts.append(f'<rect x="{mx(0.05):.1f}" y="{my(1.2):.1f}" width="{1.1*SCALE:.1f}" height="{5.2*SCALE:.1f}" fill="{C_FURNITURE_FILL}" stroke="none"/>')
    first_flight_x1 = 0.15
    first_flight_x2 = 0.55
    first_flight_y1 = 2.0
    first_flight_y2 = 4.1
    num_treads = 8
    for i in range(num_treads+1):
        ty = first_flight_y1 + (first_flight_y2 - first_flight_y1) * i / num_treads
        parts.append(line_m(first_flight_x1, ty, first_flight_x2, ty, stroke=C_STAIR, sw=1))
    parts.append(line_m(first_flight_x1, first_flight_y1, first_flight_x1, first_flight_y2, stroke=C_STAIR, sw=0.8))
    parts.append(line_m(first_flight_x2, first_flight_y1, first_flight_x2, first_flight_y2, stroke=C_STAIR, sw=0.8))
    land_x1 = 0.15
    land_x2 = 1.1
    land_y1 = 4.1
    land_y2 = 4.9
    parts.append(f'<rect x="{mx(land_x1):.1f}" y="{my(land_y1):.1f}" width="{(land_x2-land_x1)*SCALE:.1f}" height="{(land_y2-land_y1)*SCALE:.1f}" fill="{C_VOID_FILL}" stroke="{C_STAIR}" stroke-width="0.8"/>')
    parts.append(text_m((land_x1+land_x2)/2, (land_y1+land_y2)/2, "休息平台", size=8, color=C_STAIR, anchor="middle"))
    second_x1 = 0.65
    second_x2 = 1.1
    second_y1 = 2.6
    second_y2 = 4.9
    num_treads2 = 8
    for i in range(num_treads2+1):
        ty = second_y1 + (second_y2 - second_y1) * i / num_treads2
        parts.append(line_m(second_x1, ty, second_x2, ty, stroke=C_STAIR, sw=1))
    parts.append(line_m(second_x1, second_y1, second_x1, second_y2, stroke=C_STAIR, sw=0.8))
    parts.append(line_m(second_x2, second_y1, second_x2, second_y2, stroke=C_STAIR, sw=0.8))
    parts.append(line_m(0.6, 2.0, 0.6, 4.1, stroke=C_STAIR, sw=0.8, extra='stroke-dasharray="3,2"'))
    parts.append(line_m(0.6, 2.6, 0.6, 4.9, stroke=C_STAIR, sw=0.8, extra='stroke-dasharray="3,2"'))
    parts.append(f'<line x1="{mx((first_flight_x1+first_flight_x2)/2):.1f}" y1="{my(first_flight_y2-0.1):.1f}" x2="{mx((first_flight_x1+first_flight_x2)/2):.1f}" y2="{my(first_flight_y1+0.3):.1f}" stroke="{C_ROOM_NAME}" stroke-width="2.5" marker-end="url(#arrowUpL1)"/>')
    parts.append(text_m((first_flight_x1+first_flight_x2)/2, first_flight_y1+0.15, "UP", size=13, color=C_ROOM_NAME, weight="700"))
    parts.append(f'<rect x="{mx(0.08):.1f}" y="{my(2.2):.1f}" width="{0.42*SCALE:.1f}" height="{1.6*SCALE:.1f}" fill="url(#hatchL1)" stroke="{C_STAIR}" stroke-width="0.7" stroke-dasharray="3,2"/>')
    parts.append(text_m(0.3, 3.2, "梯下储物", size=7, color=C_STAIR, anchor="middle"))

    # FURNITURE
    # Entry
    parts.append(rect_m(0.1, 0.1, 1.0, 0.25, fill=C_FURNITURE_FILL))
    parts.append(text_m(0.6, 0.27, "鞋柜", size=7, color=C_FURNITURE))
    parts.append(rect_m(2.15, 2.0, 0.25, 0.8, fill=C_FURNITURE_FILL))
    parts.append(text_m(2.45, 2.4, "换鞋凳", size=7, color=C_FURNITURE, anchor="start"))
    # Kitchen
    parts.append(rect_m(2.5, 0.1, 4.6, 0.55, fill=C_FURNITURE_FILL))
    parts.append(rect_m(3.0, 0.15, 0.7, 0.4, fill="none", extra='rx="2"'))
    parts.append(text_m(3.35, 0.42, "灶具", size=7, color=C_FURNITURE))
    parts.append(rect_m(5.5, 0.15, 0.7, 0.35, fill="none", extra='rx="2"'))
    parts.append(text_m(5.85, 0.38, "水槽", size=7, color=C_FURNITURE))
    parts.append(rect_m(6.7, 0.65, 0.4, 1.95, fill=C_FURNITURE_FILL))
    parts.append(rect_m(4.8, 1.3, 2.0, 0.8, fill=C_FURNITURE_FILL, sw=1.2))
    parts.append(text_m(5.8, 1.78, "中岛 2000×800", size=8, color=C_FURNITURE, weight="600"))
    parts.append(rect_m(2.5, 0.65, 0.7, 0.65, fill=C_FURNITURE_FILL, extra='rx="2"'))
    parts.append(text_m(2.85, 1.05, "冰箱", size=7, color=C_FURNITURE))
    # Bath
    parts.append(rect_m(7.5, 0.3, 0.5, 0.6, fill="none", extra='rx="4"'))
    parts.append(text_m(7.75, 0.68, "坐便", size=7, color=C_FURNITURE))
    parts.append(rect_m(10.3, 0.2, 0.85, 1.2, fill="none", sw=0.8, extra='stroke-dasharray="3,2"'))
    parts.append(text_m(10.7, 0.85, "淋浴", size=7, color=C_FURNITURE))
    parts.append(rect_m(8.5, 1.6, 1.3, 0.45, fill=C_FURNITURE_FILL))
    parts.append(text_m(9.15, 1.9, "洗手台", size=7, color=C_FURNITURE))
    parts.append(rect_m(10.4, 1.6, 0.6, 0.9, fill=C_FURNITURE_FILL, extra='rx="2"'))
    parts.append(text_m(10.7, 2.1, "洗衣", size=7, color=C_FURNITURE))
    parts.append(text_m(10.7, 2.35, "烘干", size=6, color=C_FURNITURE))
    # Dining
    parts.append(circle_m(5.2, 4.2, 0.6, fill=C_FURNITURE_FILL, sw=1.2))
    parts.append(circle_m(5.2, 4.2, 0.15, fill="none", sw=0.8))
    parts.append(text_m(5.2, 4.25, "餐桌", size=8, color=C_FURNITURE, weight="600"))
    for cx, cy in [(5.2, 3.4),(5.2, 5.0),(4.4, 4.2),(6.0, 4.2)]:
        parts.append(rect_m(cx-0.15, cy-0.15, 0.3, 0.3, fill=C_FURNITURE_FILL, extra='rx="3"'))
    # Living
    parts.append(rect_m(3.5, 8.2, 4.0, 0.7, fill=C_FURNITURE_FILL, sw=1.2, extra='rx="3"'))
    parts.append(rect_m(7.0, 6.5, 0.8, 1.8, fill=C_FURNITURE_FILL, sw=1.2, extra='rx="3"'))
    parts.append(text_m(5.5, 8.65, "L型沙发", size=8, color=C_FURNITURE, weight="600"))
    parts.append(rect_m(4.8, 7.0, 1.4, 0.6, fill=C_FURNITURE_FILL, extra='rx="2"'))
    parts.append(text_m(5.5, 7.38, "茶几", size=7, color=C_FURNITURE))
    parts.append(rect_m(3.0, 5.3, 3.0, 0.25, fill=C_FURNITURE_FILL))
    parts.append(text_m(4.5, 5.5, "电视柜", size=7, color=C_FURNITURE))
    parts.append(rect_m(12.25, 5.0, 0.45, 3.0, fill=C_FURNITURE_FILL, sw=1.2))
    parts.append(text_m(12.5, 6.5, "书", size=7, color=C_FURNITURE, anchor="middle", extra=f'transform="rotate(-90,{mx(12.5):.1f},{my(6.5):.1f})"'))
    parts.append(text_m(12.5, 6.7, "柜", size=7, color=C_FURNITURE, anchor="middle", extra=f'transform="rotate(-90,{mx(12.5):.1f},{my(6.7):.1f})"'))
    parts.append(circle_m(3.0, 7.8, 0.15, fill="none", sw=1.2))
    parts.append(line_m(3.0, 7.95, 3.0, 8.5, stroke=C_FURNITURE, sw=1.5))
    # Balcony
    parts.append(rect_m(10.5, 8.8, 0.5, 0.5, fill=C_FURNITURE_FILL, extra='rx="5"'))
    parts.append(text_m(10.75, 9.15, "椅", size=7, color=C_FURNITURE))
    parts.append(circle_m(12.0, 9.0, 0.2, fill="none", sw=0.8))
    parts.append(text_m(12.0, 9.05, "绿植", size=6, color=C_FURNITURE))

    # ROOM LABELS
    parts.append(room_label(1.2, 2.4, "玄关", 7.5, name_size=16))
    parts.append(room_label(4.8, 2.0, "厨房", 15.4, name_size=18))
    parts.append(room_label(9.2, 1.3, "客卫", 7.2, name_size=14))
    parts.append(room_label(5.2, 4.3, "餐厅", 10.8, name_size=16))
    parts.append(room_label(5.5, 6.8, "客厅", 28.5, name_size=20))
    parts.append(room_label(11.3, 9.0, "阳台", 4.8, name_size=14))
    parts.append(room_label(0.6, 5.0, "楼梯", 6.5, name_size=12))

    # DIMENSION LINES
    d1 = 0.45
    d2 = 1.00
    d3 = 1.60
    # South
    parts.append(dim_line_h(10.0, 0, 12.8, "12800 总面宽", side="south", offset_m=d3))
    parts.append(dim_line_h(10.0, 0, 1.6, "1600", side="south", offset_m=d2))
    parts.append(dim_line_h(10.0, 1.6, 12.8, "11200 主采光面", side="south", offset_m=d2))
    parts.append(dim_line_h(10.0, 1.6, 10.2, "8600 落地窗", side="south", offset_m=d1))
    parts.append(dim_line_h(10.0, 9.8, 12.8, "3000 阳台窗", side="south", offset_m=d1-0.05))
    # North
    parts.append(dim_line_h(-0.6, 4.2, 11.2, "7000 北向设备带", side="north", offset_m=d3))
    parts.append(dim_line_h(-0.6, 4.0, 7.2, "3200 厨房窗", side="north", offset_m=d2))
    parts.append(dim_line_h(-0.6, 10.0, 11.2, "1200", side="north", offset_m=d2))
    parts.append(dim_line_v(4.2, -0.6, 0, "600", side="west", offset_m=d1))
    # West
    parts.append(dim_line_v(0, -0.6, 10.0, "10600 总进深", side="west", offset_m=d3))
    parts.append(dim_line_v(0, 0, 3.6, "3600", side="west", offset_m=d2))
    parts.append(dim_line_v(0, 3.6, 9.0, "5400", side="west", offset_m=d2))
    parts.append(dim_line_v(0, 1.275, 2.325, "1050 入户门", side="west", offset_m=d1))
    # East
    parts.append(dim_line_v(12.8, 1.2, 8.0, "6800", side="east", offset_m=d3))
    parts.append(dim_line_v(12.8, 8.0, 10.0, "2000 阳台", side="east", offset_m=d3))
    parts.append(dim_line_v(12.8, 1.2, 10.0, "8800", side="east", offset_m=d2))
    parts.append(dim_line_h(1.2, 11.2, 12.8, "1600", side="north", offset_m=d1))

    # COMPASS
    cx_n, cy_n = 1290, 100
    r_n = 28
    parts.append(f'<circle cx="{cx_n}" cy="{cy_n}" r="{r_n}" fill="white" stroke="{C_ROOM_NAME}" stroke-width="1.2"/>')
    parts.append(f'<polygon points="{cx_n},{cy_n-r_n+5} {cx_n-7},{cy_n+8} {cx_n},{cy_n+2} {cx_n+7},{cy_n+8}" fill="{C_ROOM_NAME}"/>')
    parts.append(f'<text x="{cx_n}" y="{cy_n-r_n-5}" font-size="14" fill="{C_ROOM_NAME}" text-anchor="middle" font-weight="700" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">N</text>')
    parts.append(f'<text x="{cx_n}" y="{cy_n+r_n+18}" font-size="10" fill="{C_AREA}" text-anchor="middle" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">南 · 江景方向 ↓</text>')

    # LEGEND
    leg_x = 1130
    leg_y = 140
    leg_w = 250
    leg_h = 560
    parts.append(f'<rect x="{leg_x}" y="{leg_y}" width="{leg_w}" height="{leg_h}" fill="white" stroke="{C_DIM}" stroke-width="0.8"/>')
    parts.append(f'<text x="{leg_x+leg_w/2}" y="{leg_y+22}" font-size="14" fill="{C_ROOM_NAME}" text-anchor="middle" font-weight="700" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">图 例</text>')
    ly = leg_y + 50
    labels = [
        "外墙 (6px 实线)", "内墙 (3px 实线)", "窗 (四线符号)",
        "平开门 (门扇+开启弧)", "推拉门 (轨道+错位门扇)", "楼梯 (UP=上楼方向)",
        "家具 (浅灰线稿)", "尺寸线 (三圈外置)",
    ]
    items = ["wall_outer","wall_inner","window","door_swing","door_slide","stair_up","furniture","dim"]
    for i, (item, label) in enumerate(zip(items, labels)):
        y = ly + i * 28
        if item == "wall_outer":
            parts.append(f'<line x1="{leg_x+15}" y1="{y}" x2="{leg_x+55}" y2="{y}" stroke="{C_OUTER_WALL}" stroke-width="6" stroke-linecap="square"/>')
        elif item == "wall_inner":
            parts.append(f'<line x1="{leg_x+15}" y1="{y}" x2="{leg_x+55}" y2="{y}" stroke="{C_INNER_WALL}" stroke-width="3" stroke-linecap="square"/>')
        elif item == "window":
            for off in [-3, -1, 1, 3]:
                parts.append(f'<line x1="{leg_x+15}" y1="{y+off}" x2="{leg_x+55}" y2="{y+off}" stroke="{C_WINDOW}" stroke-width="1"/>')
        elif item == "door_swing":
            parts.append(f'<line x1="{leg_x+15}" y1="{y}" x2="{leg_x+15}" y2="{y-25}" stroke="{C_DOOR}" stroke-width="2" stroke-linecap="round"/>')
            parts.append(f'<path d="M {leg_x+15} {y-25} A 25 25 0 0 1 {leg_x+40} {y}" fill="none" stroke="{C_DOOR}" stroke-width="1.2"/>')
        elif item == "door_slide":
            parts.append(f'<line x1="{leg_x+17}" y1="{y-2}" x2="{leg_x+37}" y2="{y-2}" stroke="{C_DOOR}" stroke-width="3" opacity="0.7" stroke-linecap="round"/>')
            parts.append(f'<line x1="{leg_x+27}" y1="{y+4}" x2="{leg_x+53}" y2="{y+4}" stroke="{C_DOOR}" stroke-width="3" opacity="0.7" stroke-linecap="round"/>')
            parts.append(f'<line x1="{leg_x+15}" y1="{y-8}" x2="{leg_x+55}" y2="{y-8}" stroke="{C_DOOR}" stroke-width="0.6"/>')
            parts.append(f'<line x1="{leg_x+15}" y1="{y+8}" x2="{leg_x+55}" y2="{y+8}" stroke="{C_DOOR}" stroke-width="0.6"/>')
        elif item == "stair_up":
            for j in range(4):
                parts.append(f'<line x1="{leg_x+15}" y1="{y-12+j*6}" x2="{leg_x+55}" y2="{y-12+j*6}" stroke="{C_STAIR}" stroke-width="1"/>')
            parts.append(f'<polygon points="{leg_x+35},{y-20} {leg_x+31},{y-12} {leg_x+39},{y-12}" fill="{C_ROOM_NAME}"/>')
            parts.append(f'<text x="{leg_x+35}" y="{y-22}" font-size="7" fill="{C_ROOM_NAME}" text-anchor="middle" font-weight="700">UP</text>')
        elif item == "furniture":
            parts.append(f'<rect x="{leg_x+15}" y="{y-8}" width="40" height="14" fill="{C_FURNITURE_FILL}" stroke="{C_FURNITURE}" stroke-width="1"/>')
        elif item == "dim":
            parts.append(f'<line x1="{leg_x+15}" y1="{y}" x2="{leg_x+55}" y2="{y}" stroke="{C_DIM}" stroke-width="0.8"/>')
            parts.append(f'<line x1="{leg_x+15}" y1="{y-4}" x2="{leg_x+15}" y2="{y+4}" stroke="{C_DIM}" stroke-width="0.8"/>')
            parts.append(f'<line x1="{leg_x+55}" y1="{y-4}" x2="{leg_x+55}" y2="{y+4}" stroke="{C_DIM}" stroke-width="0.8"/>')
        parts.append(f'<text x="{leg_x+70}" y="{y+4}" font-size="11" fill="{C_ROOM_NAME}" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">{label}</text>')
    sy = ly + len(labels)*28 + 15
    parts.append(f'<line x1="{leg_x+10}" y1="{sy}" x2="{leg_x+leg_w-10}" y2="{sy}" stroke="{C_DIM}" stroke-width="0.5"/>')
    sy += 20
    parts.append(f'<text x="{leg_x+leg_w/2}" y="{sy}" font-size="13" fill="{C_ROOM_NAME}" text-anchor="middle" font-weight="700" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">房间面积表</text>')
    sy += 10
    rooms_l1 = [("玄关","7.5"),("楼梯/储物","6.5"),("厨房","15.4"),("客卫+家政","7.2"),("餐厅","10.8"),("客厅(通高)","28.5"),("阳台","4.8")]
    for name, area in rooms_l1:
        sy += 18
        parts.append(f'<text x="{leg_x+15}" y="{sy}" font-size="10" fill="{C_AREA}" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">{name}</text>')
        parts.append(f'<text x="{leg_x+leg_w-15}" y="{sy}" font-size="10" fill="{C_AREA}" text-anchor="end" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">{area} ㎡</text>')
    sy += 12
    parts.append(f'<line x1="{leg_x+10}" y1="{sy}" x2="{leg_x+leg_w-10}" y2="{sy}" stroke="{C_ROOM_NAME}" stroke-width="1"/>')
    sy += 18
    parts.append(f'<text x="{leg_x+15}" y="{sy}" font-size="11" fill="{C_ROOM_NAME}" font-weight="700" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">一层合计</text>')
    parts.append(f'<text x="{leg_x+leg_w-15}" y="{sy}" font-size="11" fill="{C_ROOM_NAME}" font-weight="700" text-anchor="end" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">约 80 ㎡</text>')
    parts.append(text_m(7.2, 10.75, "南 · 江景方向", size=11, color=C_AREA, anchor="middle"))

    parts.append('</svg>')
    return "\n".join(parts)


# ============================================================
# LEVEL 2
# ============================================================
def gen_level2():
    parts = []
    parts.append(f'<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{CW}" height="{CH}" viewBox="0 0 {CW} {CH}" style="background:{C_BG};">')
    parts.append('<defs>')
    parts.append('<pattern id="hatchVoidL2" patternUnits="userSpaceOnUse" width="7" height="7" patternTransform="rotate(45)">')
    parts.append(f'<line x1="0" y1="0" x2="0" y2="7" stroke="{C_VOID_LINE}" stroke-width="0.6"/>')
    parts.append('</pattern>')
    parts.append(f'<marker id="arrowDnL2" markerWidth="12" markerHeight="12" refX="6" refY="6" orient="auto">')
    parts.append(f'<path d="M0,0 L6,12 L12,0 Z" fill="{C_ROOM_NAME}"/>')
    parts.append('</marker>')
    parts.append('</defs>')

    parts.append(f'<text x="{CW/2}" y="32" font-size="20" fill="{C_ROOM_NAME}" text-anchor="middle" font-weight="700" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">二层平面图 · 私密休息层</text>')
    parts.append(f'<text x="{CW/2}" y="52" font-size="11" fill="{C_AREA}" text-anchor="middle" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">比例 1:72 · 单位：米（m）· 斜线区域挑空至一层客厅 · 约 52㎡</text>')

    # L1 outline reference
    l1_verts = [(0,0),(4.2,0),(4.2,-0.6),(11.2,-0.6),(11.2,1.2),(12.8,1.2),(12.8,10.0),(1.6,10.0),(1.6,9.0),(0,9.0)]
    pts_str = " ".join(f"{mx(v[0]):.1f},{my(v[1]):.1f}" for v in l1_verts)
    parts.append(f'<polyline points="{pts_str}" fill="none" stroke="{C_REF_OUTLINE}" stroke-width="1.2" stroke-dasharray="8,4" stroke-linejoin="round"/>')
    parts.append(text_m(6.4, 10.25, "—— 一层外轮廓对位参考（浅灰虚线） ——", size=9, color=C_REF_OUTLINE, anchor="middle"))

    # VOID AREAS
    parts.append(f'<rect x="{mx(1.2):.1f}" y="{my(5.2):.1f}" width="{6.0*SCALE:.1f}" height="{4.8*SCALE:.1f}" fill="{C_VOID_FILL}" stroke="none"/>')
    parts.append(f'<rect x="{mx(1.2):.1f}" y="{my(5.2):.1f}" width="{6.0*SCALE:.1f}" height="{4.8*SCALE:.1f}" fill="url(#hatchVoidL2)" stroke="none" opacity="0.7"/>')
    parts.append(f'<rect x="{mx(11.2):.1f}" y="{my(1.2):.1f}" width="{1.6*SCALE:.1f}" height="{8.8*SCALE:.1f}" fill="{C_VOID_FILL}" stroke="none"/>')
    parts.append(f'<rect x="{mx(11.2):.1f}" y="{my(1.2):.1f}" width="{1.6*SCALE:.1f}" height="{8.8*SCALE:.1f}" fill="url(#hatchVoidL2)" stroke="none" opacity="0.7"/>')
    parts.append(text_m(4.2, 7.5, "挑空至客厅", size=16, color=C_VOID_LINE, weight="700"))
    parts.append(text_m(4.2, 7.85, "OPEN TO BELOW", size=10, color=C_VOID_LINE))

    # L2 SLAB FILL
    l2_verts = [(0,0),(4.2,0),(4.2,-0.6),(11.2,-0.6),(11.2,10.0),(7.2,10.0),(7.2,5.2),(1.2,5.2),(1.2,9.0),(0,9.0)]
    pts_str2 = " ".join(f"{mx(v[0]):.1f},{my(v[1]):.1f}" for v in l2_verts)
    parts.append(f'<polygon points="{pts_str2}" fill="{C_BG}" stroke="none"/>')

    # GLASS RAILINGS
    parts.append(line_m(1.2, 5.2, 7.2, 5.2, stroke=C_RAILING, sw=W_RAILING))
    parts.append(line_m(1.2, 5.2+0.05, 7.2, 5.2+0.05, stroke=C_RAILING, sw=0.8))
    parts.append(line_m(11.2, 5.2, 11.2, 6.8, stroke=C_RAILING, sw=W_RAILING))
    parts.append(line_m(11.2+0.05, 5.2, 11.2+0.05, 6.8, stroke=C_RAILING, sw=0.8))
    parts.append(line_m(1.2, 5.2, 1.2, 9.0, stroke=C_RAILING, sw=W_RAILING))
    parts.append(line_m(1.2+0.05, 5.2, 1.2+0.05, 9.0, stroke=C_RAILING, sw=0.8))
    for px in [1.2, 2.5, 4.0, 5.5, 7.2, 11.2]:
        parts.append(f'<circle cx="{mx(px):.1f}" cy="{my(5.2):.1f}" r="2" fill="{C_RAILING}"/>')
    for py in [6.0, 7.0, 8.0, 9.0]:
        parts.append(f'<circle cx="{mx(1.2):.1f}" cy="{my(py):.1f}" r="2" fill="{C_RAILING}"/>')
    parts.append(f'<circle cx="{mx(11.2):.1f}" cy="{my(6.0):.1f}" r="2" fill="{C_RAILING}"/>')
    parts.append(text_m(4.2, 5.05, "玻璃护栏 / GLASS RAILING", size=8, color=C_RAILING, anchor="middle"))

    # OUTER WALLS L2
    parts.append(wall_line(0, 0, 4.2, 0, outer=True))
    parts.append(wall_line(4.2, 0, 4.2, -0.6, outer=True))
    parts.append(wall_line(4.2, -0.6, 4.4, -0.6, outer=True))
    # studio window 4.4~7.2
    parts.append(wall_line(7.2, -0.6, 10.3, -0.6, outer=True))
    # bath window 10.3~11.2
    parts.append(wall_line(11.2, -0.6, 11.2, 1.2, outer=True))
    parts.append(wall_line(11.2, 1.2, 11.2, 5.2, outer=True))
    parts.append(wall_line(11.2, 6.8, 11.2, 10.0, outer=True))
    # south wall with window
    parts.append(wall_line(7.2, 10.0, 7.4, 10.0, outer=True))
    # master bed window 7.4~11.2
    parts.append(wall_line(7.2, 6.8, 7.2, 10.0, outer=True))
    parts.append(wall_line(0, 9.0, 0, 0, outer=True))
    parts.append(wall_line(1.2, 9.0, 0, 9.0, outer=True))

    # WINDOWS L2
    parts.append(window_line(4.4, -0.6, 7.2, -0.6))
    parts.append(window_line(10.3, -0.6, 11.2, -0.6))
    parts.append(window_line(7.4, 10.0, 11.2, 10.0))
    parts.append(window_line(11.2, 7.2, 11.2, 9.0))

    # INNER WALLS L2
    parts.append(wall_line(1.2, 0, 1.2, 3.0))
    parts.append(wall_line(1.2, 3.8, 1.2, 5.2))
    parts.append(wall_line(2.4, 0, 2.4, 5.2))
    parts.append(wall_line(7.2, -0.6, 7.2, 0))
    parts.append(wall_line(7.2, 0, 7.2, 5.2))
    parts.append(wall_line(7.2, 2.6, 8.0, 2.6))
    # bath door 8.0~8.8
    parts.append(wall_line(8.8, 2.6, 11.2, 2.6))
    parts.append(wall_line(2.4, 5.2, 3.2, 5.2))
    # studio door 3.2~4.1
    parts.append(wall_line(4.1, 5.2, 7.2, 5.2))
    parts.append(wall_line(7.2, 5.2, 7.2, 5.5))
    # bedroom door 5.5~6.4
    parts.append(wall_line(7.2, 6.4, 7.2, 6.8))
    parts.append(wall_line(9.8, 5.2, 9.8, 6.8))

    # DOORS L2
    parts.append(door_swing((3.2, 5.2), (4.1, 5.2), (3.2, 4.3), 0.9))
    parts.append(door_swing((8.0, 2.6), (8.8, 2.6), (8.0, 3.4), 0.8))
    parts.append(door_swing((7.2, 5.5), (7.2, 6.4), (6.3, 5.5), 0.9))
    parts.append(sliding_door(9.8, 5.4, 9.8, 6.4))

    # STAIRS L2
    parts.append(f'<rect x="{mx(0.15):.1f}" y="{my(2.8):.1f}" width="{0.95*SCALE:.1f}" height="{2.1*SCALE:.1f}" fill="{C_FURNITURE_FILL}" stroke="{C_STAIR}" stroke-width="0.8" stroke-dasharray="4,2"/>')
    for i in range(5):
        ty = 3.0 + i*0.3
        parts.append(line_m(0.2, ty, 1.05, ty, stroke=C_STAIR, sw=1))
    parts.append(text_m(0.6, 2.7, "楼梯口", size=8, color=C_STAIR, weight="600"))
    parts.append(f'<line x1="{mx(0.62):.1f}" y1="{my(3.2):.1f}" x2="{mx(0.62):.1f}" y2="{my(4.6):.1f}" stroke="{C_ROOM_NAME}" stroke-width="2.5" marker-end="url(#arrowDnL2)"/>')
    parts.append(text_m(0.62, 4.85, "DN", size=13, color=C_ROOM_NAME, weight="700"))

    # FURNITURE L2
    # Studio
    parts.append(rect_m(2.8, 0.15, 2.6, 0.55, fill=C_FURNITURE_FILL, sw=1.2))
    parts.append(text_m(4.1, 0.5, "2.6m 设计桌", size=8, color=C_FURNITURE, weight="600"))
    parts.append(rect_m(3.8, 0.0, 0.5, 0.2, fill=C_FURNITURE_FILL, extra='rx="1"'))
    parts.append(text_m(4.05, -0.05, "显示器", size=6, color=C_FURNITURE))
    parts.append(rect_m(3.8, 1.0, 0.5, 0.5, fill=C_FURNITURE_FILL, extra='rx="6"'))
    parts.append(text_m(4.05, 1.35, "工作椅", size=7, color=C_FURNITURE))
    parts.append(rect_m(2.45, 1.0, 0.3, 2.5, fill=C_FURNITURE_FILL))
    parts.append(text_m(2.3, 2.25, "资", size=7, color=C_FURNITURE, anchor="end", extra=f'transform="rotate(-90,{mx(2.3):.1f},{my(2.25):.1f})"'))
    parts.append(text_m(2.3, 2.45, "料", size=7, color=C_FURNITURE, anchor="end", extra=f'transform="rotate(-90,{mx(2.3):.1f},{my(2.45):.1f})"'))
    parts.append(text_m(2.3, 2.65, "柜", size=7, color=C_FURNITURE, anchor="end", extra=f'transform="rotate(-90,{mx(2.3):.1f},{my(2.65):.1f})"'))
    parts.append(rect_m(3.0, 4.6, 4.0, 0.4, fill=C_FURNITURE_FILL))
    parts.append(text_m(5.0, 4.88, "矮柜", size=7, color=C_FURNITURE))
    parts.append(rect_m(7.05, 0.8, 0.1, 1.7, fill=C_FURNITURE_FILL, sw=1.2))
    parts.append(text_m(7.3, 1.7, "软木板", size=6, color=C_FURNITURE, anchor="start"))
    # Master Bath
    parts.append(rect_m(7.5, 0.1, 3.0, 0.7, fill=C_FURNITURE_FILL, sw=1.2, extra='rx="4"'))
    parts.append(text_m(9.0, 0.55, "浴缸", size=8, color=C_FURNITURE, weight="600"))
    parts.append(rect_m(7.5, 1.0, 0.5, 0.55, fill="none", extra='rx="4"'))
    parts.append(text_m(7.75, 1.35, "坐便", size=7, color=C_FURNITURE))
    parts.append(rect_m(8.5, 1.8, 2.3, 0.45, fill=C_FURNITURE_FILL))
    parts.append(text_m(9.65, 2.1, "双台盆洗手台", size=7, color=C_FURNITURE))
    # Closet
    parts.append(rect_m(7.25, 5.3, 0.35, 1.4, fill=C_FURNITURE_FILL))
    parts.append(rect_m(9.45, 5.3, 0.35, 1.4, fill=C_FURNITURE_FILL))
    parts.append(rect_m(7.6, 6.6, 1.8, 0.2, fill=C_FURNITURE_FILL))
    parts.append(line_m(7.4, 5.5, 7.4, 6.5, stroke=C_FURNITURE, sw=1.5))
    parts.append(line_m(9.65, 5.5, 9.65, 6.5, stroke=C_FURNITURE, sw=1.5))
    parts.append(line_m(8.0, 6.68, 9.2, 6.68, stroke=C_FURNITURE, sw=1.5))
    parts.append(text_m(8.5, 6.05, "衣帽间", size=9, color=C_FURNITURE, weight="600"))
    # Master Bedroom
    parts.append(rect_m(8.0, 8.2, 1.8, 1.0, fill=C_FURNITURE_FILL, sw=1.2, extra='rx="3"'))
    parts.append(text_m(8.9, 8.8, "1.8m 床", size=9, color=C_FURNITURE, weight="600"))
    parts.append(rect_m(8.15, 8.25, 0.55, 0.25, fill=C_FURNITURE_FILL, extra='rx="2"'))
    parts.append(rect_m(9.1, 8.25, 0.55, 0.25, fill=C_FURNITURE_FILL, extra='rx="2"'))
    parts.append(rect_m(7.6, 8.5, 0.4, 0.4, fill=C_FURNITURE_FILL, extra='rx="2"'))
    parts.append(rect_m(9.8, 8.5, 0.4, 0.4, fill=C_FURNITURE_FILL, extra='rx="2"'))
    parts.append(rect_m(10.7, 7.0, 0.4, 2.5, fill=C_FURNITURE_FILL, sw=1.2))
    parts.append(text_m(10.95, 8.3, "衣柜", size=7, color=C_FURNITURE, anchor="middle", extra=f'transform="rotate(-90,{mx(10.95):.1f},{my(8.3):.1f})"'))
    parts.append(rect_m(8.55, 7.6, 0.5, 0.4, fill=C_FURNITURE_FILL, extra='rx="4"'))
    parts.append(text_m(8.8, 7.88, "榻", size=6, color=C_FURNITURE))
    # Bridge/Corridor
    parts.append(rect_m(0.3, 7.0, 0.6, 0.6, fill=C_FURNITURE_FILL, extra='rx="5"'))
    parts.append(text_m(0.6, 7.4, "阅读椅", size=7, color=C_FURNITURE))
    parts.append(circle_m(0.5, 6.4, 0.15, fill=C_FURNITURE_FILL))

    # ROOM LABELS L2
    parts.append(room_label(0.6, 4.0, "楼梯口", 5.0, name_size=12))
    parts.append(room_label(0.6, 8.0, "走廊", 3.5, name_size=12))
    parts.append(room_label(4.8, 2.8, "工作室", 18.5, name_size=18))
    parts.append(room_label(9.2, 1.3, "主卫", 5.8, name_size=14))
    parts.append(room_label(4.2, 4.5, "桥廊", 7.2, name_size=14))
    parts.append(room_label(8.5, 6.0, "衣帽间", 4.5, name_size=13))
    parts.append(room_label(9.2, 8.4, "主卧", 12.5, name_size=18))

    # DIMENSIONS L2
    d1 = 0.45; d2 = 1.00; d3 = 1.60
    parts.append(dim_line_h(10.0, 0, 11.2, "11200 楼板总宽", side="south", offset_m=d3))
    parts.append(dim_line_h(10.0, 0, 1.6, "1600", side="south", offset_m=d2))
    parts.append(dim_line_h(10.0, 7.2, 11.2, "4000", side="south", offset_m=d2))
    parts.append(dim_line_h(10.0, 7.4, 11.2, "3800 主卧落地窗", side="south", offset_m=d1))
    parts.append(dim_line_h(-0.6, 4.2, 11.2, "7000 北向设备带", side="north", offset_m=d3))
    parts.append(dim_line_h(-0.6, 4.4, 7.2, "2800 工作室窗", side="north", offset_m=d2))
    parts.append(dim_line_h(-0.6, 10.3, 11.2, "900", side="north", offset_m=d2))
    parts.append(dim_line_v(0, -0.6, 10.0, "10600 总进深", side="west", offset_m=d3))
    parts.append(dim_line_v(0, 0, 5.2, "5200", side="west", offset_m=d2))
    parts.append(dim_line_v(0, 5.2, 9.0, "3800 走廊", side="west", offset_m=d2))
    parts.append(dim_line_v(11.2, -0.6, 5.2, "5800", side="east", offset_m=d3))
    parts.append(dim_line_v(11.2, 6.8, 10.0, "3200 主卧", side="east", offset_m=d3))
    parts.append(dim_line_v(11.2, 7.2, 9.0, "1800 内窗", side="east", offset_m=d1))
    parts.append(dim_line_h(1.2, 11.2, 12.8, "1600 (挑空)", side="north", offset_m=d1))

    # COMPASS
    cx_n, cy_n = 1290, 100
    r_n = 28
    parts.append(f'<circle cx="{cx_n}" cy="{cy_n}" r="{r_n}" fill="white" stroke="{C_ROOM_NAME}" stroke-width="1.2"/>')
    parts.append(f'<polygon points="{cx_n},{cy_n-r_n+5} {cx_n-7},{cy_n+8} {cx_n},{cy_n+2} {cx_n+7},{cy_n+8}" fill="{C_ROOM_NAME}"/>')
    parts.append(f'<text x="{cx_n}" y="{cy_n-r_n-5}" font-size="14" fill="{C_ROOM_NAME}" text-anchor="middle" font-weight="700" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">N</text>')
    parts.append(f'<text x="{cx_n}" y="{cy_n+r_n+18}" font-size="10" fill="{C_AREA}" text-anchor="middle" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">南 · 江景方向 ↓</text>')

    # LEGEND L2
    leg_x = 1130; leg_y = 140; leg_w = 250; leg_h = 600
    parts.append(f'<rect x="{leg_x}" y="{leg_y}" width="{leg_w}" height="{leg_h}" fill="white" stroke="{C_DIM}" stroke-width="0.8"/>')
    parts.append(f'<text x="{leg_x+leg_w/2}" y="{leg_y+22}" font-size="14" fill="{C_ROOM_NAME}" text-anchor="middle" font-weight="700" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">图 例</text>')
    ly = leg_y + 50
    l2_labels = [
        "二层外墙 (6px 实线)", "内墙 (3px 实线)", "一层轮廓 (浅灰虚线)",
        "挑空区 (斜线填充)", "玻璃护栏 (双线)", "窗 (四线符号)",
        "平开门 (门扇+开启弧)", "推拉门 (轨道+错位门扇)", "楼梯 (DN=下楼方向)",
    ]
    l2_items = ["wall_outer","wall_inner","l1_outline","void","railing","window","door_swing","door_slide","stair_dn"]
    for i, (item, label) in enumerate(zip(l2_items, l2_labels)):
        y = ly + i * 28
        if item == "wall_outer":
            parts.append(f'<line x1="{leg_x+15}" y1="{y}" x2="{leg_x+55}" y2="{y}" stroke="{C_OUTER_WALL}" stroke-width="6" stroke-linecap="square"/>')
        elif item == "wall_inner":
            parts.append(f'<line x1="{leg_x+15}" y1="{y}" x2="{leg_x+55}" y2="{y}" stroke="{C_INNER_WALL}" stroke-width="3" stroke-linecap="square"/>')
        elif item == "l1_outline":
            parts.append(f'<line x1="{leg_x+15}" y1="{y}" x2="{leg_x+55}" y2="{y}" stroke="{C_REF_OUTLINE}" stroke-width="1.2" stroke-dasharray="6,3"/>')
        elif item == "void":
            parts.append(f'<rect x="{leg_x+15}" y="{y-8}" width="40" height="14" fill="{C_VOID_FILL}" stroke="{C_VOID_LINE}" stroke-width="0.8"/>')
            parts.append(f'<rect x="{leg_x+15}" y="{y-8}" width="40" height="14" fill="url(#hatchVoidL2)" opacity="0.7"/>')
        elif item == "railing":
            parts.append(f'<line x1="{leg_x+15}" y1="{y}" x2="{leg_x+55}" y2="{y}" stroke="{C_RAILING}" stroke-width="1.5"/>')
            parts.append(f'<line x1="{leg_x+15}" y1="{y+4}" x2="{leg_x+55}" y2="{y+4}" stroke="{C_RAILING}" stroke-width="0.8"/>')
        elif item == "window":
            for off in [-3, -1, 1, 3]:
                parts.append(f'<line x1="{leg_x+15}" y1="{y+off}" x2="{leg_x+55}" y2="{y+off}" stroke="{C_WINDOW}" stroke-width="1"/>')
        elif item == "door_swing":
            parts.append(f'<line x1="{leg_x+15}" y1="{y}" x2="{leg_x+15}" y2="{y-25}" stroke="{C_DOOR}" stroke-width="2" stroke-linecap="round"/>')
            parts.append(f'<path d="M {leg_x+15} {y-25} A 25 25 0 0 1 {leg_x+40} {y}" fill="none" stroke="{C_DOOR}" stroke-width="1.2"/>')
        elif item == "door_slide":
            parts.append(f'<line x1="{leg_x+17}" y1="{y-2}" x2="{leg_x+37}" y2="{y-2}" stroke="{C_DOOR}" stroke-width="3" opacity="0.7" stroke-linecap="round"/>')
            parts.append(f'<line x1="{leg_x+27}" y1="{y+4}" x2="{leg_x+53}" y2="{y+4}" stroke="{C_DOOR}" stroke-width="3" opacity="0.7" stroke-linecap="round"/>')
            parts.append(f'<line x1="{leg_x+15}" y1="{y-8}" x2="{leg_x+55}" y2="{y-8}" stroke="{C_DOOR}" stroke-width="0.6"/>')
            parts.append(f'<line x1="{leg_x+15}" y1="{y+8}" x2="{leg_x+55}" y2="{y+8}" stroke="{C_DOOR}" stroke-width="0.6"/>')
        elif item == "stair_dn":
            for j in range(4):
                parts.append(f'<line x1="{leg_x+15}" y1="{y-12+j*6}" x2="{leg_x+55}" y2="{y-12+j*6}" stroke="{C_STAIR}" stroke-width="1"/>')
            parts.append(f'<polygon points="{leg_x+35},{y+4} {leg_x+31},{y-4} {leg_x+39},{y-4}" fill="{C_ROOM_NAME}"/>')
            parts.append(f'<text x="{leg_x+35}" y="{y+16}" font-size="7" fill="{C_ROOM_NAME}" text-anchor="middle" font-weight="700">DN</text>')
        parts.append(f'<text x="{leg_x+70}" y="{y+4}" font-size="11" fill="{C_ROOM_NAME}" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">{label}</text>')
    sy = ly + len(l2_labels)*28 + 15
    parts.append(f'<line x1="{leg_x+10}" y1="{sy}" x2="{leg_x+leg_w-10}" y2="{sy}" stroke="{C_DIM}" stroke-width="0.5"/>')
    sy += 20
    parts.append(f'<text x="{leg_x+leg_w/2}" y="{sy}" font-size="13" fill="{C_ROOM_NAME}" text-anchor="middle" font-weight="700" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">房间面积表</text>')
    sy += 10
    rooms_l2 = [("楼梯口/走廊","8.5"),("工作室","18.5"),("主卫","5.8"),("桥廊","7.2"),("衣帽间","4.5"),("主卧","12.5")]
    for name, area in rooms_l2:
        sy += 18
        parts.append(f'<text x="{leg_x+15}" y="{sy}" font-size="10" fill="{C_AREA}" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">{name}</text>')
        parts.append(f'<text x="{leg_x+leg_w-15}" y="{sy}" font-size="10" fill="{C_AREA}" text-anchor="end" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">{area} ㎡</text>')
    sy += 12
    parts.append(f'<line x1="{leg_x+10}" y1="{sy}" x2="{leg_x+leg_w-10}" y2="{sy}" stroke="{C_ROOM_NAME}" stroke-width="1"/>')
    sy += 18
    parts.append(f'<text x="{leg_x+15}" y="{sy}" font-size="11" fill="{C_ROOM_NAME}" font-weight="700" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">二层合计</text>')
    parts.append(f'<text x="{leg_x+leg_w-15}" y="{sy}" font-size="11" fill="{C_ROOM_NAME}" font-weight="700" text-anchor="end" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif">约 52 ㎡</text>')
    parts.append(text_m(6.0, 10.35, "南 · 江景方向", size=11, color=C_AREA, anchor="middle"))

    parts.append('</svg>')
    return "\n".join(parts)


if __name__ == "__main__":
    import os
    out_dir = r"e:\Agent_reply\ita-river-loft-room.design-project\assets"
    os.makedirs(out_dir, exist_ok=True)

    svg1 = gen_level1()
    with open(os.path.join(out_dir, "floor_plan_level1.svg"), "w", encoding="utf-8") as f:
        f.write(svg1)
    print("Wrote floor_plan_level1.svg")

    svg2 = gen_level2()
    with open(os.path.join(out_dir, "floor_plan_level2.svg"), "w", encoding="utf-8") as f:
        f.write(svg2)
    print("Wrote floor_plan_level2.svg")

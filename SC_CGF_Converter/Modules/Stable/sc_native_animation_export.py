# SC Native Animation Export; Python standard library only.
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
import struct
import zlib
from collections import defaultdict
from pathlib import Path
FLT_MAX = 3.4028235e+38
_NUM_RE = re.compile('[-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?')

def _leaf(name):
    return str(name).strip().replace('\\', '/').rsplit('/', 1)[-1].split(':')[-1]

def _joint_key(name):
    return re.sub('[^a-z0-9]', '', _leaf(name).lower())

def _unique(seq):
    out, seen = ([], set())
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _motion(s):
    n = str(s).lower()
    if 'compress' in n or 'compression' in n:
        return 'compress'
    if 'deploy' in n or 'extend' in n or 'extension' in n:
        return 'deploy'
    if 'retract' in n:
        return 'retract'
    return 'unknown'

def _family(s):
    n = str(s).lower()
    if 'backleft' in n or 'back_left' in n or 'left_wing' in n or ('landing_gear_left' in n):
        return 'left'
    if 'backright' in n or 'back_right' in n or 'right_wing' in n or ('landing_gear_right' in n):
        return 'right'
    if 'lg_front' in n or 'landinggear_front' in n or 'landinggearfront' in n or ('front_landing' in n) or ('landing_gear_front' in n):
        return 'front'
    return 'unknown'

def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

def _vlen(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])

def _sample_timed(seq, times, qtime):
    if not seq:
        return (0.0, 0.0, 0.0)
    n = min(len(seq), len(times))
    if n <= 0:
        return seq[0]
    if n == 1 or qtime <= times[0]:
        return seq[0]
    if qtime >= times[n - 1]:
        return seq[n - 1]
    lo, hi = (0, n - 1)
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if times[mid] <= qtime:
            lo = mid
        else:
            hi = mid
    t0, t1 = (float(times[lo]), float(times[hi]))
    if t1 <= t0:
        return seq[lo]
    a = (qtime - t0) / (t1 - t0)
    v0, v1 = (seq[lo], seq[hi])
    return tuple((v0[k] + (v1[k] - v0[k]) * a for k in range(3)))

def _parse_htr(path):
    lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()
    tracks, mode, current = ({}, None, None)
    for raw in lines:
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            sec = line[1:-1].strip()
            sl = sec.lower()
            current = None
            if sl in ('header', 'segmentnames&hierarchy', 'baseposition'):
                mode = sl
            else:
                mode = 'track'
                current = sec
                tracks.setdefault(current, [])
            continue
        if mode == 'track' and current:
            p = line.split()
            if len(p) >= 7:
                try:
                    tracks[current].append((float(p[1]), float(p[2]), float(p[3])))
                except Exception:
                    pass
    fam = _family(path.name)
    if fam == 'unknown':
        fam = _family(' '.join(tracks))
    return {'path': path, 'tracks': tracks, 'family': fam, 'motion': _motion(path.name)}

def _read_names_from_usda(path):
    text = path.read_text(encoding='utf-8', errors='ignore')
    out = []
    for m in re.finditer('(?:uniform\\s+)?token\\[\\]\\s+joints\\s*=\\s*\\[(.*?)\\]', text, re.S):
        out.extend((_leaf(q) for q in re.findall('"([^"]+)"', m.group(1))))
    return _unique(out)

def _build_hash_name_map(roots):
    result = {}
    for root in roots:
        if not root or not root.exists(): continue
        for path in root.rglob('*.usda'):
            for name in _read_names_from_usda(path):
                h = zlib.crc32(name.encode('utf-8')) & 0xffffffff
                if h in result and result[h] != name:
                    raise ValueError('Controller-name CRC collision')
                result[h] = name
    return result

def _extract_dba_refs(raw):
    out = []
    for m in re.finditer(b'[A-Za-z0-9_.$/\\\\-]+\\.dba', raw, re.I):
        out.append(m.group(0).decode('utf-8', errors='ignore').replace('\\', '/'))
    return _unique(out)

def _resolve_dba(context):
    inp = Path(context.get('input') or '') if context.get('input') else None
    obj = Path(context.get('objectdir') or '') if context.get('objectdir') else None
    ref = Path(context.get('reference') or '') if context.get('reference') else None
    if inp and inp.exists() and (inp.suffix.lower() == '.dba'):
        return inp
    if inp and inp.exists():
        cp = inp.with_suffix('.chrparams')
        if cp.exists():
            for rel in _extract_dba_refs(cp.read_bytes()):
                relp = Path(rel)
                candidates = []
                if obj:
                    candidates.append(obj / relp)
                candidates.append(cp.parent / relp.name)
                for c in candidates:
                    if c.exists():
                        return c
    if ref and ref.exists():
        hits = list(ref.rglob('*.dba'))
        for p in hits:
            if p.name.lower() == 'landing_gear.dba':
                return p
        if len(hits) == 1:
            return hits[0]
    raise RuntimeError('Could not resolve DBA from Input/.chrparams or Reference folder.')

def _metadata_caf_paths(data):
    return _unique((m.group(0).decode('utf-8', errors='ignore').replace('\\', '/') for m in re.finditer(b'(?:animations|Animations)[A-Za-z0-9_.$/\\\\-]*\\.caf', data)))

def _parse_blocks(data):
    blocks, pos = ([], 0)
    while True:
        off = data.find(b'#dba', pos)
        if off < 0:
            break
        if off + 12 > len(data):
            break
        bone_count, magic, block_size = struct.unpack_from('<HHI', data, off + 4)
        if magic != 43605 or not 0 < bone_count <= 2048:
            pos = off + 4
            continue
        hashes_off = off + 12
        ctrl_off = hashes_off + bone_count * 4
        if ctrl_off + bone_count * 24 > len(data):
            break
        hashes = struct.unpack_from('<' + 'I' * bone_count, data, hashes_off)
        entries = []
        for i in range(bone_count):
            eoff = ctrl_off + i * 24
            vals = struct.unpack_from('<HHIIHHII', data, eoff)
            entries.append({'controller_start': eoff, 'bone_hash': hashes[i], 'num_rot_keys': vals[0], 'rot_flags': vals[1], 'rot_time_offset': vals[2], 'rot_data_offset': vals[3], 'num_pos_keys': vals[4], 'pos_flags': vals[5], 'pos_time_offset': vals[6], 'pos_data_offset': vals[7]})
        blocks.append({'offset': off, 'bone_count': bone_count, 'block_size': block_size, 'entries': entries})
        pos = ctrl_off + bone_count * 24
    return blocks

def _decode_bitset_times(data, abs_off, count, bit_order):
    if abs_off is None or abs_off < 0 or abs_off + 4 > len(data):
        return None
    start, end = struct.unpack_from('<HH', data, abs_off)
    if end < start or end - start > 65535:
        return None
    slots = end - start + 1
    nbytes = (slots + 7) // 8
    p = abs_off + 4
    if p + nbytes > len(data):
        return None
    bits = data[p:p + nbytes]
    times = []
    for i in range(slots):
        byte = bits[i // 8]
        bit = i % 8
        mask = 1 << bit if bit_order == 'LSB' else 1 << 7 - bit
        if byte & mask:
            times.append(start + i)
    return {'start': start, 'end': end, 'slots': slots, 'bitset_bytes': nbytes, 'times': times, 'popcount': len(times), 'count_matches': len(times) == count, 'preview_times': times[:20], 'last_times': times[-10:] if times else [], 'raw_bitset_hex': bits.hex(' ')}

def _active(scale):
    return math.isfinite(scale) and abs(scale) < FLT_MAX * 0.5

def _decode_positions_reference(data, e):
    """Reference Star Citizen position layout.

    C0: float3 per key.
    C1: 24-byte scale/offset header, then XYZ u16 interleaved per key.
    C2: 24-byte scale/offset header, then PLANAR u16 arrays:
        all X keys, then all Y keys, then all Z keys for active axes only.
    """
    count = int(e['num_pos_keys'])
    flags = int(e['pos_flags'])
    fmt = flags >> 8 & 255
    off = e['controller_start'] + int(e['pos_data_offset'])
    if count <= 0 or off < 0 or off >= len(data):
        return []
    if fmt == 192:
        need = count * 12
        if off + need > len(data):
            return []
        return [struct.unpack_from('<fff', data, off + i * 12) for i in range(count)]
    if fmt not in (193, 194) or off + 24 > len(data):
        return []
    scale = struct.unpack_from('<fff', data, off)
    offset = struct.unpack_from('<fff', data, off + 12)
    if fmt == 193:
        p = off + 24
        out = []
        for _ in range(count):
            vals = []
            for axis in range(3):
                if p + 2 > len(data):
                    return out
                u = struct.unpack_from('<H', data, p)[0]
                p += 2
                vals.append(u * scale[axis] + offset[axis])
            out.append(tuple(vals))
        return out
    active = [_active(x) for x in scale]
    p = off + 24
    planes = [None, None, None]
    for axis in range(3):
        if not active[axis]:
            continue
        byte_count = count * 2
        if p + byte_count > len(data):
            return []
        planes[axis] = struct.unpack_from('<' + 'H' * count, data, p)
        p += byte_count
    out = []
    for i in range(count):
        vals = []
        for axis in range(3):
            if active[axis]:
                vals.append(planes[axis][i] * scale[axis] + offset[axis])
            else:
                vals.append(offset[axis])
        out.append(tuple(vals))
    return out

def _qnorm(q):
    n = math.sqrt(sum((float(x) * float(x) for x in q)))
    return (1.0, 0.0, 0.0, 0.0) if n < 1e-12 else tuple((float(x) / n for x in q))

def _qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return _qnorm((aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw))

def _qinv(q):
    w, x, y, z = _qnorm(q)
    return (w, -x, -y, -z)

def _qaxis(axis, deg):
    a = math.radians(deg) * 0.5
    c, s = (math.cos(a), math.sin(a))
    if axis == 'X':
        return (c, s, 0.0, 0.0)
    if axis == 'Y':
        return (c, 0.0, s, 0.0)
    return (c, 0.0, 0.0, s)

def _qnlerp(a, b, t):
    a, b = (_qnorm(a), _qnorm(b))
    if sum((x * y for x, y in zip(a, b))) < 0.0:
        b = tuple((-x for x in b))
    return _qnorm(tuple((a[i] + (b[i] - a[i]) * t for i in range(4))))

def _sample_q_timed(seq, times, qtime):
    n = min(len(seq), len(times))
    if n <= 0:
        return (1.0, 0.0, 0.0, 0.0)
    if n == 1 or qtime <= times[0]:
        return seq[0]
    if qtime >= times[n - 1]:
        return seq[n - 1]
    lo, hi = (0, n - 1)
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if times[mid] <= qtime:
            lo = mid
        else:
            hi = mid
    t0, t1 = (float(times[lo]), float(times[hi]))
    a = 0.0 if t1 <= t0 else (qtime - t0) / (t1 - t0)
    return _qnlerp(seq[lo], seq[hi], a)

def _sign_extend_i16(u):
    return u - 65536 if u & 32768 else u

def _decode_rotations_reference(data, e):
    count = int(e['num_rot_keys'])
    flags = int(e['rot_flags'])
    fmt = flags >> 8 & 255
    off = int(e['controller_start']) + int(e['rot_data_offset'])
    if count <= 0 or off < 0 or off >= len(data):
        return []
    if fmt == 128:
        if off + count * 16 > len(data):
            return []
        out = []
        for i in range(count):
            x, y, z, w = struct.unpack_from('<ffff', data, off + i * 16)
            out.append(_qnorm((w, x, y, z)))
        return out
    if fmt != 130 or off + count * 6 > len(data):
        return []
    out = []
    inv_scale = 1.0 / 23170.0
    rng = 1.0 / math.sqrt(2.0)
    for i in range(count):
        s0, s1, s2 = struct.unpack_from('<HHH', data, off + i * 6)
        idx = s2 >> 14 & 3
        b0 = s0 & 32767
        b1 = s1 * 2 + (s0 >> 15 & 1) & 32767
        b2 = (s1 >> 14) + _sign_extend_i16(s2) * 4 & 32767
        r0 = b0 * inv_scale - rng
        r1 = b1 * inv_scale - rng
        r2 = b2 * inv_scale - rng
        largest = math.sqrt(max(0.0, 1.0 - r0 * r0 - r1 * r1 - r2 * r2))
        if idx == 0:
            x, y, z, w = (largest, r0, r1, r2)
        elif idx == 1:
            x, y, z, w = (r0, largest, r1, r2)
        elif idx == 2:
            x, y, z, w = (r0, r1, largest, r2)
        else:
            x, y, z, w = (r0, r1, r2, largest)
        out.append(_qnorm((w, x, y, z)))
    return out

def _qrotate(q, v):
    w, x, y, z = _qnorm(q)
    vx, vy, vz = (float(a) for a in v)
    tx, ty, tz = (2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx))
    return (vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx)

def _mat3_to_q(m):
    r00, r01, r02 = m[0]
    r10, r11, r12 = m[1]
    r20, r21, r22 = m[2]
    tr = r00 + r11 + r22
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        q = (0.25 * s, (r21 - r12) / s, (r02 - r20) / s, (r10 - r01) / s)
    elif r00 > r11 and r00 > r22:
        s = math.sqrt(max(1e-12, 1.0 + r00 - r11 - r22)) * 2.0
        q = ((r21 - r12) / s, 0.25 * s, (r01 + r10) / s, (r02 + r20) / s)
    elif r11 > r22:
        s = math.sqrt(max(1e-12, 1.0 + r11 - r00 - r22)) * 2.0
        q = ((r02 - r20) / s, (r01 + r10) / s, 0.25 * s, (r12 + r21) / s)
    else:
        s = math.sqrt(max(1e-12, 1.0 + r22 - r00 - r11)) * 2.0
        q = ((r10 - r01) / s, (r02 + r20) / s, (r12 + r21) / s, 0.25 * s)
    return _qnorm(q)

def _parse_matrix_array(text, field_name):
    m = re.search(f'(?:uniform\\s+)?matrix4d\\[\\]\\s+{re.escape(field_name)}\\s*=\\s*\\[(.*?)\\]\\s*(?:\\n|\\r|$)', text, re.S)
    if not m:
        return []
    vals = [float(x) for x in _NUM_RE.findall(m.group(1))]
    out = []
    for i in range(0, len(vals) - 15, 16):
        a = vals[i:i + 16]
        out.append(((a[0], a[1], a[2], a[3]), (a[4], a[5], a[6], a[7]), (a[8], a[9], a[10], a[11]), (a[12], a[13], a[14], a[15])))
    return out

def _parse_skeleton_usda(path):
    text = path.read_text(encoding='utf-8', errors='ignore')
    jm = re.search('(?:uniform\\s+)?token\\[\\]\\s+joints\\s*=\\s*\\[(.*?)\\]', text, re.S)
    if not jm:
        return None
    joints = re.findall('"([^"]+)"', jm.group(1))
    rest = _parse_matrix_array(text, 'restTransforms')
    bind = _parse_matrix_array(text, 'bindTransforms')
    if not joints or not rest:
        return None
    entries = []
    path_to_index = {j: i for i, j in enumerate(joints)}
    for i, j in enumerate(joints):
        mat = rest[i] if i < len(rest) else None
        if mat:
            pos = (mat[3][0], mat[3][1], mat[3][2])
            rot = _mat3_to_q(tuple((tuple((mat[c][r] for c in range(3))) for r in range(3))))
        else:
            pos, rot = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))
        parent_path = j.rsplit('/', 1)[0] if '/' in j else None
        parent = path_to_index.get(parent_path, -1) if parent_path else -1
        entries.append({'index': i, 'path': j, 'name': _leaf(j), 'key': _joint_key(j), 'parent': parent, 'rest_pos': pos, 'rest_rot': rot, 'bind': bind[i] if i < len(bind) else None})
    return {'path': path, 'joints': entries, 'text': text}

def _raw_block_tracks(data, block, name_map):
    out = {}
    for e in block['entries']:
        name = name_map.get(e['bone_hash'])
        if not name:
            continue
        pos = _decode_positions_reference(data, e)
        pt = _reference_times(data, e, 'position')
        rot = _decode_rotations_reference(data, e)
        rt = _reference_times(data, e, 'rotation')
        out[_joint_key(name)] = {'name': name, 'entry': e, 'pos': pos, 'pos_times': pt, 'rot': rot, 'rot_times': rt}
    return out

def _world_compose(parent_pos, parent_rot, local_pos, local_rot):
    rp = _qrotate(parent_rot, local_pos)
    pos = (parent_pos[0] + rp[0], parent_pos[1] + rp[1], parent_pos[2] + rp[2])
    rot = _qmul(parent_rot, local_rot)
    return (pos, rot)
MATH_REVISION = '20261007-vector-length-usd-row-matrix'

def _strict_times(data, entry, which):
    prefix = 'rot' if which == 'rotation' else 'pos'
    count, flags = (entry['num_' + prefix + '_keys'], entry[prefix + '_flags'])
    offset = entry[prefix + '_time_offset']
    if not count:
        return []
    if not flags:
        raise ValueError(f'{which}: keys present with zero format flags')
    if not offset:
        return list(range(count))
    start = entry['controller_start'] + offset
    fmt = flags & 15
    if start < 0:
        raise ValueError('Negative time offset')
    if fmt == 0 and start + count <= len(data):
        times = list(data[start:start + count])
    elif fmt == 1 and start + count * 2 <= len(data):
        times = list(struct.unpack_from('<' + 'H' * count, data, start))
    elif fmt == 2:
        result = _decode_bitset_times(data, start, count, 'LSB')
        if not result or not result['count_matches']:
            raise ValueError(f'{which}: bitmap population differs from key count; no uniform fallback')
        times = result['times']
    else:
        raise ValueError(f'{which}: unsupported or truncated time format {fmt}')
    if len(times) != count or any((a >= b for a, b in zip(times, times[1:]))):
        raise ValueError(f'{which}: invalid key count or ordering')
    return times
_reference_times = _strict_times

def _load_raw(data, block, names):
    hashes = [entry['bone_hash'] for entry in block['entries']]
    if len(hashes) != len(set(hashes)):
        raise ValueError('Duplicate bone hashes in DBA clip')
    result = _raw_block_tracks(data, block, names)
    for key, tr in result.items():
        e = tr['entry']
        for channel, prefix in [('position', 'pos'), ('rotation', 'rot')]:
            if len(tr[prefix]) != e['num_' + prefix + '_keys']:
                raise ValueError(f"{tr['name']}: unsupported/truncated {channel} data")
            if any((not all((math.isfinite(v) for v in row)) for row in tr[prefix])):
                raise ValueError(f"{tr['name']}: non-finite {channel} data")
    all_times = [t for tr in result.values() for field in ['pos_times', 'rot_times'] for t in tr[field]]
    bounds = (min(all_times), max(all_times)) if all_times else (0, 0)
    return (result, bounds)

def _sample_at(track, frame):
    pos = _sample_timed(track['pos'], track['pos_times'], frame) if track and track['pos'] else None
    rot = _sample_q_timed(track['rot'], track['rot_times'], frame) if track and track['rot'] else None
    return (pos, rot)

def _world_at(sk, raw, frame, positions=True):
    memo = {}

    def ev(index):
        if index in memo:
            return memo[index]
        joint = sk['joints'][index]
        pos, rot = _sample_at(raw.get(joint['key']), frame)
        if pos is None or not positions:
            pos = joint['rest_pos']
        if rot is None:
            rot = joint['rest_rot']
        if joint['parent'] >= 0:
            p, q = ev(joint['parent'])
            memo[index] = _world_compose(p, q, pos, rot)
        else:
            memo[index] = (pos, rot)
        return memo[index]
    for j in sk['joints']:
        ev(j['index'])
    return {j['key']: memo[j['index']] for j in sk['joints']}

def _math_checks():
    max_norm_error = 0.0
    max_inverse_error = 0.0
    for q in [_qaxis('X', 90), _qaxis('Y', -37), _qnorm((0.3, -0.2, 0.7, 0.5))]:
        for v in [(0.0, 0.0, 0.0), (0.02, -0.4, 2.7), (2000.0, -37.0, 93.0)]:
            r = _qrotate(q, v)
            max_norm_error = max(max_norm_error, abs(_vlen(r) - _vlen(v)))
            max_inverse_error = max(max_inverse_error, _vlen(_vsub(_qrotate(_qinv(q), r), v)))
    if max_norm_error > 1e-08 or max_inverse_error > 1e-08:
        raise AssertionError('Vector rotation changes magnitude')
    return {'max_vector_length_error': max_norm_error, 'max_inverse_roundtrip_error': max_inverse_error}

def _usda_vec(v):
    return '(' + ', '.join((format(float(x), '.10g') for x in v)) + ')'

def _usda_matrix(matrix):
    return '(' + ', '.join((_usda_vec(row) for row in matrix)) + ')'

def _matrix53(p, q):
    return tuple((tuple(_qrotate(q, axis)) + (0.0,) for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))) + (tuple(p) + (1.0,),)

def _checks53():
    checks = _math_checks()
    m = _matrix53((2.0, 3.0, 4.0), _qaxis('Z', 90))
    assert _vlen(_vsub(m[0][:3], (0.0, 1.0, 0.0))) < 1e-10
    assert _vlen(_vsub(m[1][:3], (-1.0, 0.0, 0.0))) < 1e-10
    assert _vlen(_vsub(m[3][:3], (2.0, 3.0, 4.0))) < 1e-10
    tip = tuple((m[3][i] + m[0][i] for i in range(3)))
    assert _vlen(_vsub(tip, (2.0, 4.0, 4.0))) < 1e-10
    return {'transform_math': checks, 'known_90deg_row_matrix_and_marker_vertex': 'PASS'}

def _export_usda(sk, tracks, fps, path, source_label):
    alltimes = [v for tr in tracks.values() for field in ['pos_times', 'rot_times'] for v in tr[field]]
    if not alltimes:
        raise ValueError('No samples to export')
    start, end = (min(alltimes), max(alltimes))
    times = sorted(set(alltimes) | set(range(math.ceil(start), math.floor(end) + 1)))
    rest = _parse_matrix_array(sk['text'], 'restTransforms')
    bind = _parse_matrix_array(sk['text'], 'bindTransforms')
    if len(rest) != len(sk['joints']) or len(bind) != len(sk['joints']):
        raise ValueError('Incomplete source skeleton matrices')
    root = 'SC_Native_Animation'
    lines = ['#usda 1.0', '(', '    defaultPrim = "' + root + '"', '    doc = ' + json.dumps(source_label), '    startTimeCode = ' + str(start), '    endTimeCode = ' + str(end), '    framesPerSecond = ' + str(fps), '    timeCodesPerSecond = ' + str(fps), '    metersPerUnit = 1', '    upAxis = "Z"', ')', 'def Xform "' + root + '"', '{', '    def SkelRoot "Armature"', '    {', '        def Skeleton "Skeleton" (prepend apiSchemas = ["SkelBindingAPI"])', '        {']
    names = '[' + ', '.join((json.dumps(j['path']) for j in sk['joints'])) + ']'
    lines += ['            uniform token[] joints = ' + names, '            uniform matrix4d[] bindTransforms = [' + ', '.join((_usda_matrix(mat) for mat in bind)) + ']', '            uniform matrix4d[] restTransforms = [' + ', '.join((_usda_matrix(mat) for mat in rest)) + ']', '            rel skel:animationSource = </' + root + '/Armature/Animation>', '        }', '        def SkelAnimation "Animation"', '        {', '            uniform token[] joints = ' + names]
    positions = []
    rotations = []
    previous = {}
    for frame in times:
        ps = []
        qs = []
        for j in sk['joints']:
            pos, rot = _sample_at(tracks.get(j['key']), frame)
            if pos is None:
                pos = j['rest_pos']
            if rot is None:
                rot = j['rest_rot']
            if j['key'] in previous and sum((a * b for a, b in zip(rot, previous[j['key']]))) < 0:
                rot = tuple((-v for v in rot))
            previous[j['key']] = rot
            ps.append(_usda_vec(pos))
            qs.append(_usda_vec(rot))
        positions.append('                ' + format(frame, '.10g') + ': [' + ', '.join(ps) + '],')
        rotations.append('                ' + format(frame, '.10g') + ': [' + ', '.join(qs) + '],')
    lines += ['            float3[] translations.timeSamples = {', *positions, '            }', '            quatf[] rotations.timeSamples = {', *rotations, '            }', '            half3[] scales = [' + ', '.join(('(1, 1, 1)' for _ in sk['joints'])) + ']', '        }', '    }', '}']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'path': str(path), 'source': source_label, 'joint_count': len(sk['joints']), 'sample_count': len(times), 'start': start, 'end': end, 'fps': fps, 'animated_source_bones': [tr['name'] for tr in tracks.values()]}
PROCESSOR_META = {'id': 'sc_native_animation_export', 'name': 'SC Native Animation Export', 'version': '0.3.7', 'status': 'stable', 'profiles': ['StarCitizen'], 'stage': 'export', 'description': 'Marker-free decoded DBA animation using original CGF skeleton names, axes and bind pose. Also writes a Max loader for an existing rig.'}

def _native_skeleton(root, family):
    candidates = []
    for path in sorted(root.rglob('*.usda')):
        if 'NATIVE_ANIMATION' in path.parts or '_anim_' in path.name.lower():
            continue
        sk = _parse_skeleton_usda(path)
        if sk and (_family(path.name) == family or _family(' '.join((j['name'] for j in sk['joints']))) == family):
            candidates.append(sk)
    if not candidates:
        return None
    signatures = {tuple(((j['path'], j['rest_pos'], j['rest_rot'], j['bind']) for j in sk['joints'])) for sk in candidates}
    if len(signatures) != 1:
        raise ValueError('Multiple different ' + family + ' skeletons; use a folder containing only the intended source rig')
    return candidates[0]

def _validate_source(sk):
    joints = sk['joints']
    keys = [j['key'] for j in joints]
    if len(set(keys)) != len(keys):
        raise ValueError('Source joint leaf names are ambiguous')
    rest = _parse_matrix_array(sk['text'], 'restTransforms')
    bind = _parse_matrix_array(sk['text'], 'bindTransforms')
    if len(rest) != len(joints) or len(bind) != len(joints):
        raise ValueError('Incomplete rest/bind matrices')
    for j, m in zip(joints, rest):
        if j['parent'] >= j['index']:
            raise ValueError('Source hierarchy must list parents before children')
        if not all((math.isfinite(v) for row in m for v in row)):
            raise ValueError('Non-finite source transform')
        for a in range(3):
            for b in range(3):
                dot = sum((m[a][c] * m[b][c] for c in range(3)))
                if abs(dot - (1 if a == b else 0)) > 0.0001:
                    raise ValueError('Scaled/sheared source rest transform is unsupported')
    if not re.search('\\bmetersPerUnit\\s*=\\s*1(?:\\.0)?\\s', sk['text']) or not re.search('\\bupAxis\\s*=\\s*"Z"', sk['text']):
        raise ValueError('Expected existing CGF source convention: metersPerUnit=1, Z-up')
    return True

def _max_vec(v):
    return '[' + ', '.join((format(float(x), '.10g') for x in v)) + ']'

def _max_loader(sk, raw, bounds, fps, path):
    times = sorted(set((v for tr in raw.values() for field in ('pos_times', 'rot_times') for v in tr[field])) | set(range(math.ceil(bounds[0]), math.floor(bounds[1]) + 1)))
    joints = sk['joints']
    worlds = [_world_at(sk, raw, f) for f in times]
    lines = ['/* SC Native Animation Export 0.3.7. Original CGF axes; no pivot correction.', '   Import the original CHR/SKIN rig, select its root, then run this file.', '   Bakes this clip on existing joints. Undo restores the previous animation.', '   Exact joint names required; source rig must be unscaled and unrotated in world. */', '(', '    local jointNames = #(' + ', '.join((json.dumps(j['name']) for j in joints)) + ')', '    local parentIndices = #(' + ', '.join((str(j['parent'] + 1) for j in joints)) + ')', '    local frames = #(' + ', '.join((format(f, '.10g') for f in times)) + ')', '    local poses = #(']
    for n, w in enumerate(worlds):
        mats = []
        for j in joints:
            mat = _matrix53(*w[j['key']])
            mats.append('#(' + ', '.join((_max_vec(row[:3]) for row in mat)) + ')')
        lines.append('        #(' + ', '.join(mats) + ')' + (',' if n < len(worlds) - 1 else ''))
    lines += ['    )', '    local pool = #()', '    local targets = #()', '    fn collectRig n nodes = (if findItem nodes n == 0 do (append nodes n; for c in n.children do collectRig c nodes))', '    if selection.count > 0 then (for n in selection do collectRig n pool) else (pool = objects as array)', '    for name in jointNames do', '    (', '        local hits = for n in pool where ((toLower n.name) == (toLower name)) collect n', '        if hits.count != 1 do throw ("Expected one existing joint named: " + name + ". Select the intended original rig root.")', '        append targets hits[1]', '    )', '    for i = 1 to targets.count do', '    (', '        if parentIndices[i] > 0 and targets[i].parent != targets[parentIndices[i]] do throw ("Hierarchy differs from source: " + jointNames[i])', '        local tm = targets[i].transform', '        if abs((length tm.row1)-1.0)>0.0001 or abs((length tm.row2)-1.0)>0.0001 or abs((length tm.row3)-1.0)>0.0001 do throw "Scaled rig: use the original CGF import before applying animation."', '    )', '    local metersToUnits = units.decodeValue "1m"', '    undo "SC Native Animation" on', '    (', '        frameRate = ' + str(int(round(fps))), '        animationRange = interval (frames[1]*ticksPerFrame) (frames[frames.count]*ticksPerFrame)', '        animate on', '        (', '            for f = 1 to frames.count do at time (frames[f]*ticksPerFrame)', '            (', '                for j = 1 to targets.count do', '                (', '                    local rows = poses[f][j]', '                    targets[j].transform = matrix3 rows[1] rows[2] rows[3] (rows[4]*metersToUnits)', '                )', '            )', '        )', '    )', '    format "SC Native Animation: applied % joints, % frames; original CGF axes.\\n" targets.count frames.count', ')']
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'path': str(path), 'joint_count': len(joints), 'sample_count': len(times), 'new_scene_objects': 0}

def run(context):
    checks = _checks53()
    dba = _resolve_dba(context)
    data = dba.read_bytes()
    if not context.get('output'):
        raise ValueError('Set Output to the original CHR USDA skeleton folder')
    out = Path(context['output'])
    roots = [out]
    if context.get('reference'):
        roots.append(Path(context['reference']))
    names = _build_hash_name_map(roots)
    blocks = _parse_blocks(data)
    paths = _metadata_caf_paths(data)
    if len(blocks) != len(paths):
        raise ValueError('DBA clip catalog and descriptor count mismatch')
    dest = Path(context.get('native_output') or out / 'NATIVE_ANIMATION')
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    exports = []
    used = set()
    for block, caf in zip(blocks, paths):
        clip = Path(caf).stem
        family = _family(clip)
        row = {'clip': clip, 'family': family}
        rows.append(row)
        if family == 'unknown':
            row.update(status='skipped', reason='No supported skeleton-family mapping')
            continue
        if not re.fullmatch('[A-Za-z0-9_\\-]+', clip) or clip.lower() in used:
            raise ValueError('Unsafe or duplicate clip output name: ' + clip)
        used.add(clip.lower())
        sk = _native_skeleton(out, family)
        if not sk:
            row.update(status='skipped', reason='Missing matching source CHR skeleton')
            continue
        _validate_source(sk)
        match = re.search('\\bframesPerSecond\\s*=\\s*([0-9.]+)', sk['text'])
        fps = float(match.group(1)) if match else 30.0
        if not math.isfinite(fps) or fps <= 0 or fps != round(fps):
            raise ValueError('Native Max loader requires a positive integer source FPS')
        raw, bounds = _load_raw(data, block, names)
        unresolved = [hex(e['bone_hash']) for e in block['entries'] if e['bone_hash'] not in names]
        outside = [tr['name'] for k, tr in raw.items() if k not in {j['key'] for j in sk['joints']}]
        if unresolved or outside:
            row.update(status='blocked', unresolved_controller_hashes=unresolved, tracks_outside_skeleton=outside)
            continue
        path = dest / (clip + '_anim_NATIVE.usda')
        item = _export_usda(sk, raw, fps, path, 'Decoded DBA animation in original CGF-Converter coordinates; no HTR adjustment or diagnostic meshes.')
        item['max_loader'] = _max_loader(sk, raw, bounds, fps, dest / (clip + '_ApplyToExistingRig.ms'))
        exports.append(item)
        row.update(status='exported', source_skeleton=str(sk['path']), skeleton_sha256=hashlib.sha256(Path(sk['path']).read_bytes()).hexdigest(), output=str(path))
    if not exports:
        raise ValueError('No native clips exported; check matching original CHR skeletons and controller names')
    result = {'processor': 'SC Native Animation Export', 'version': '0.3.7', 'status': 'exported' if not any((r['status'] == 'blocked' for r in rows)) else 'partial', 'math_revision': MATH_REVISION, 'dba_sha256': hashlib.sha256(data).hexdigest(), 'checks': checks, 'clips': rows, 'generated_files': exports, 'coordinate_convention': 'Original CGF CHR rest/bind transforms and joint axes. No legacy HTR adjustment. HTR is not used.', 'limitations': 'Validated on the supplied Hornet front/left DBA clips. Skipped families need their matching skeleton. Max loader requires exact unique original joint names, matching hierarchy and original unscaled/unrotated import. Existing clip keys are overwritten at sampled frames; keys outside the clip remain. Max loader and skinned playback need a live Max check. FPS comes from source CHR.'}
    report = dest / 'SC_Native_Animation_Report.json'
    result['report_path'] = str(report)
    report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=PROCESSOR_META['description'])
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--reference')
    parser.add_argument('--native-output')
    print(json.dumps(run(vars(parser.parse_args())), indent=2))

#!/usr/bin/env python3
"""Минимальный парсер DEX — без внешних зависимостей.

Достаёт ровно то, что нужно для восстановления утраченных классов:
  - types()      : все дескрипторы типов (Lcom/foo/Bar;)
  - fields()     : поле -> (класс, тип, имя)
  - methods()    : метод -> (класс, имя, возвращаемый тип, [параметры])
  - classes()    : класс -> (имя, флаги, предок, [интерфейсы])

Формат: https://source.android.com/docs/core/runtime/dex-format
Проверено на 4 dex из APK Delta-2.747.1486 (27 995 типов).
"""
import struct
import sys

ACC = {
    0x0001: 'public', 0x0002: 'private', 0x0004: 'protected',
    0x0008: 'static', 0x0010: 'final', 0x0020: 'synchronized',
    0x0040: 'volatile', 0x0080: 'transient', 0x0200: 'interface',
    0x0400: 'abstract', 0x0800: 'strictfp', 0x1000: 'synthetic',
    0x2000: 'annotation', 0x4000: 'enum', 0x10000: 'constructor',
    0x20000: 'declared_synchronized',
}


def read_uleb128(data, i):
    r = s = 0
    while True:
        b = data[i]
        i += 1
        r |= (b & 0x7f) << s
        if not b & 0x80:
            return r, i
        s += 7


def read_sleb128(data, i):
    r = s = 0
    while True:
        b = data[i]
        i += 1
        r |= (b & 0x7f) << s
        s += 7
        if not b & 0x80:
            if b & 0x40:
                r -= (1 << s)
            return r, i


class Dex:
    def __init__(self, path):
        self.path = path
        self.data = d = open(path, 'rb').read()
        if d[:4] != b'dex\n':
            raise ValueError('не DEX: %s' % path)
        u = lambda off: struct.unpack_from('<I', d, off)[0]
        self.string_ids_size, self.string_ids_off = u(0x38), u(0x3C)
        self.type_ids_size, self.type_ids_off = u(0x40), u(0x44)
        self.proto_ids_size, self.proto_ids_off = u(0x48), u(0x4C)
        self.field_ids_size, self.field_ids_off = u(0x50), u(0x54)
        self.method_ids_size, self.method_ids_off = u(0x58), u(0x5C)
        self.class_defs_size, self.class_defs_off = u(0x60), u(0x64)
        self._s = None
        self._t = None

    # ---------- базовые таблицы ----------
    def strings(self):
        if self._s is None:
            d, off = self.data, self.string_ids_off
            out = []
            for i in range(self.string_ids_size):
                (so,) = struct.unpack_from('<I', d, off + 4 * i)
                _, p = read_uleb128(d, so)
                e = d.index(b'\x00', p)
                out.append(d[p:e].decode('utf-8', 'replace'))
            self._s = out
        return self._s

    def types(self):
        if self._t is None:
            s, d, off = self.strings(), self.data, self.type_ids_off
            self._t = [s[struct.unpack_from('<I', d, off + 4 * i)[0]]
                       for i in range(self.type_ids_size)]
        return self._t

    def fields(self):
        """[(class_type, field_type, name)]"""
        s, t, d, off = self.strings(), self.types(), self.data, self.field_ids_off
        out = []
        for i in range(self.field_ids_size):
            ci, ti, ni = struct.unpack_from('<HHI', d, off + 8 * i)
            out.append((t[ci], t[ti], s[ni]))
        return out

    def protos(self):
        """[(return_type, (param_types...))]"""
        t, d, off = self.types(), self.data, self.proto_ids_off
        out = []
        for i in range(self.proto_ids_size):
            _shorty, ret, params_off = struct.unpack_from('<III', d, off + 12 * i)
            params = ()
            if params_off:
                n = struct.unpack_from('<I', d, params_off)[0]
                params = tuple(t[struct.unpack_from('<H', d, params_off + 4 + 2 * k)[0]]
                               for k in range(n))
            out.append((t[ret], params))
        return out

    def methods(self):
        """[(class_type, name, return_type, (params))]"""
        s, t, d, off = self.strings(), self.types(), self.data, self.method_ids_off
        protos = self.protos()
        out = []
        for i in range(self.method_ids_size):
            ci, pi, ni = struct.unpack_from('<HHI', d, off + 8 * i)
            ret, params = protos[pi]
            out.append((t[ci], s[ni], ret, params))
        return out

    def classes(self):
        """[(name, access, super, [interfaces])]"""
        t, d, off = self.types(), self.data, self.class_defs_off
        out = []
        for i in range(self.class_defs_size):
            b = off + 32 * i
            ci, acc, sup, ifaces_off = struct.unpack_from('<IIII', d, b)
            ifaces = []
            if ifaces_off:
                n = struct.unpack_from('<I', d, ifaces_off)[0]
                ifaces = [t[struct.unpack_from('<H', d, ifaces_off + 4 + 2 * k)[0]]
                          for k in range(n)]
            sup_name = t[sup] if sup != 0xFFFFFFFF else None
            out.append((t[ci], acc, sup_name, ifaces))
        return out


def main():
    total_t = total_m = total_f = 0
    for p in sys.argv[1:]:
        d = Dex(p)
        print('%-28s строк %6d  типов %6d  полей %6d  методов %6d  классов %5d'
              % (p.split('/')[-1], d.string_ids_size, d.type_ids_size,
                 d.field_ids_size, d.method_ids_size, d.class_defs_size))
        total_t += d.type_ids_size
        total_m += d.method_ids_size
        total_f += d.field_ids_size
    if len(sys.argv) > 2:
        print('ИТОГО: типов %d, полей %d, методов %d' % (total_t, total_f, total_m))


if __name__ == '__main__':
    main()

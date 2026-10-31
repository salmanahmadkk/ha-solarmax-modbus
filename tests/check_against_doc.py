"""Cross-check every register in registers.py against the protocol document tables."""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "solarmax_modbus"))
import registers as R

doc = {}
for line in open(sys.argv[1]):
    parts = [p.strip() for p in line.strip().split("|")]
    for i, p in enumerate(parts):
        m = re.fullmatch(r"(0[xX][0-9A-Fa-f]{4})\w*\s*/?", p)
        if m and i + 2 < len(parts):
            addr = int(m.group(1)[2:], 16)
            count = re.sub(r"\D", "", parts[i + 1])
            typ = parts[i + 2].replace("ing", "ing")
            rw = next((x for x in reversed(parts[i + 3:]) if x in ("RW", "R/W", "RO", "WO")), "")
            if count:
                doc.setdefault(addr, (int(count), typ, rw))
            break
print("doc registers parsed:", len(doc))

KNOWN = {  # deliberate, documented differences
    0x2009: "doc says U32; read as S32 because charging power is negative on real inverters",
    0x1A6F: "doc prints '0x1A6Fa' (typo)",
    0x5104: "doc leaves R/W blank for Derating Watt Percent",
    0x1A00: "doc lists 8 x U16 with unit ASCII = 16-character string",
    0x1A10: "doc lists 8 x U16 with unit ASCII = 16-character string",
}
dtype = {R.U16: "U16", R.S16: "S16", R.U32: "U32", R.S32: "S32", R.STR: "string"}
problems = []
for key, f in R.FIELDS.items():
    d = doc.get(f.address)
    if d is None:
        (print(f"  note  {key} 0x{f.address:04X}: {KNOWN[f.address]}") if f.address in KNOWN
         else problems.append(f"{key} 0x{f.address:04X} not in document"))
        continue
    count, typ, rw = d
    if count != f.words:
        problems.append(f"{key} 0x{f.address:04X}: {f.words} words, doc says {count}")
    if typ != dtype[f.dtype]:
        (print(f"  note  {key} 0x{f.address:04X}: {KNOWN[f.address]}") if f.address in KNOWN
         else problems.append(f"{key} 0x{f.address:04X}: type {dtype[f.dtype]}, doc says {typ}"))
for key in R.WRITABLE_KEYS:
    f = R.FIELDS[key]
    rw = doc.get(f.address, (0, "", ""))[2]
    if rw not in ("RW", "R/W"):
        (print(f"  note  write {key} 0x{f.address:04X}: {KNOWN[f.address]}") if f.address in KNOWN
         else problems.append(f"WRITE {key} 0x{f.address:04X} is '{rw}' in the doc"))
    if 0x5000 <= f.address <= 0x5118 and key != "derating_percent":
        problems.append(f"WRITE {key} touches grid-code range")
for a in range(4):
    if doc.get(0x3000 + a, (0, "", ""))[2] not in ("RW", "R/W"):
        problems.append(f"clock 0x{0x3000+a:04X} not RW")
print(f"fields checked: {len(R.FIELDS)}, writable: {len(R.WRITABLE_KEYS)}")
print("PROBLEMS:" if problems else "ALL ADDRESSES MATCH THE DOCUMENT", *problems, sep="\n  ")

"""Download student certificate PDFs from QR-decoded URLs and parse name/score.
Outputs students_data.json keyed by teacher folder.
"""
import os, sys, json, re, urllib.request, time
import pdfplumber

QR = r"D:\CLAUDE\ELEGANT\qr_results.json"
CERT_DIR = r"D:\CLAUDE\ELEGANT\assets\Student Certificates"
OUT = r"D:\CLAUDE\ELEGANT\students_data.json"

os.makedirs(CERT_DIR, exist_ok=True)

with open(QR, encoding='utf-8') as fp:
    qr_data = json.load(fp)

def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return True
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            with open(dest, 'wb') as f:
                f.write(r.read())
        return True
    except Exception as e:
        print(f"  ERR fetch {url}: {e}", flush=True)
        return False

def title_uz(s):
    """Title-case Uzbek text, preserving apostrophes."""
    return " ".join(w.capitalize() for w in s.split())

def parse_national(text):
    """Standard subject cert (biology, math, physics, etc.)"""
    out = {"kind": "national"}
    m = re.search(r"Sertifikat raqami:\s*([A-Z0-9 ]+)", text)
    if m: out["cert_no"] = m.group(1).strip()
    m = re.search(r"Familiyasi:\s*([^\n]+)", text)
    if m: out["surname"] = m.group(1).strip()
    m = re.search(r"Ismi:\s*([^\n]+)", text)
    if m: out["first_name"] = m.group(1).strip()
    m = re.search(r"Otasining ismi:\s*([^\n]+)", text)
    if m: out["father"] = m.group(1).strip()
    m = re.search(r"Umumta[ʼ'’]lim fani:\s*([^\n]+)", text)
    if m: out["subject"] = m.group(1).strip()
    # The score appears on the line BEFORE "Umumiy to'plagan bali:" because
    # extract_text orders lines that way; capture both orders.
    m = re.search(r"(\d+\.\d+)\s*\n\s*Umumiy to[‘'’]plagan bali", text)
    if not m:
        m = re.search(r"Umumiy to[‘'’]plagan bali:?\s*\n?\s*(\d+\.\d+)", text)
    if m: out["score"] = m.group(1)
    m = re.search(r"(\d+\.\d+)\s*%", text)
    if m: out["percent"] = m.group(1) + "%"
    m = re.search(r"Sertifikat darajasi:\s*\n?\s*([A-Z+\-]+)", text)
    if not m:
        m = re.search(r"\n([A-Z]\+?)\s*\nSertifikat darajasi", text)
    if not m:
        # Try line-position: grade letter often on its own line
        for line in text.split("\n"):
            line = line.strip()
            if re.fullmatch(r"[A-D][+-]?", line):
                out["grade"] = line; break
    if m and "grade" not in out: out["grade"] = m.group(1)
    m = re.search(r"Berilgan sanasi:\s*([\d.]+)", text)
    if m: out["issued"] = m.group(1)
    return out

def parse_cefr(text):
    """English language CEFR cert (positional, no labels)."""
    out = {"kind": "cefr"}
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # Format observed:
    # 0: cert code (e.g. 25BBA1476524SM)
    # 1: AD code
    # 2: SURNAME
    # 3: FIRSTNAME
    # 4: FATHERNAME
    # 5: "INGLIZ TILI <LEVEL>"
    # 6: scores like "75 75 68"
    # 7: scores
    # 8: dates
    if len(lines) >= 6:
        out["cert_no"] = lines[0]
        # Heuristic: surname is uppercase token on a line by itself
        for i, l in enumerate(lines):
            if re.fullmatch(r"[A-ZʻʼА-Я'`’]{3,}", l) and "surname" not in out:
                out["surname"] = l
                # next two lines = first name + father
                if i+1 < len(lines): out["first_name"] = lines[i+1]
                if i+2 < len(lines): out["father"] = lines[i+2]
                break
    m = re.search(r"\b(A1|A2|B1|B2|C1|C2)\b", text)
    if m: out["level"] = m.group(1)
    m = re.search(r"INGLIZ TILI\b", text)
    if m: out["subject"] = "Ingliz tili"
    # All score numbers in the cert (Listening, Reading, Writing, Speaking, Overall)
    nums = re.findall(r"\b\d{2,3}\b", text)
    # Filter to the score block - typically two consecutive lines of 2-digit numbers
    # We'll just grab the first 5 plausible (between 0 and 100)
    plausible = [int(n) for n in nums if 0 <= int(n) <= 100]
    if len(plausible) >= 4:
        out["scores"] = plausible[:5]
    m = re.search(r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})", text)
    if m:
        out["issued"] = m.group(1); out["expires"] = m.group(2)
    return out

def parse_trf(text):
    """British Council / IDP IELTS Test Report Form."""
    out = {"kind": "trf", "subject": "IELTS"}
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # surname is the first ALL-CAPS standalone line after "Candidate Details"
    try:
        idx = next(i for i, l in enumerate(lines) if l.startswith("Candidate Details"))
        rest = lines[idx+1:]
    except StopIteration:
        rest = lines
    name_lines = []
    for l in rest:
        if re.fullmatch(r"[A-Zʻʼ‘’\-' ]{2,}", l):
            name_lines.append(l)
            if len(name_lines) >= 2:
                break
    if len(name_lines) >= 2:
        out["surname"] = name_lines[0]
        out["first_name"] = name_lines[1]
    # band + level
    m = re.search(r"Listening\s+(\d\.\d)\s+Reading\s+(\d\.\d)\s+Writing\s+(\d\.\d)\s+Speaking\s+(\d\.\d)\s+Band\s+(\d\.\d)\s+(C2|C1|B2|B1|A2|A1)", text)
    if m:
        out["scores"] = {"listening": m.group(1), "reading": m.group(2), "writing": m.group(3), "speaking": m.group(4)}
        out["score"] = m.group(5)  # overall band as numeric "score"
        out["level"] = m.group(6)
    else:
        # fallback: look for any standalone band like "7.0" near "Band"
        m = re.search(r"\b(C2|C1|B2|B1|A2|A1)\b", text)
        if m: out["level"] = m.group(1)
    m = re.search(r"Centre Number\s+\S+\s+(\d{1,2}/[A-Z]{3}/\d{4})", text)
    if m: out["issued"] = m.group(1)
    m = re.search(r"Candidate Number\s+(\d+)", text)
    if m: out["cert_no"] = m.group(1)
    return out

def parse_pdf(path):
    try:
        with pdfplumber.open(path) as pdf:
            text = ""
            for p in pdf.pages:
                text += (p.extract_text() or "") + "\n"
    except Exception as e:
        return {"raw": "", "error": str(e)}
    if "Test Report Form" in text:
        out = parse_trf(text)
    elif "Sertifikat raqami:" in text:
        out = parse_national(text)
    elif "INGLIZ TILI" in text:
        out = parse_cefr(text)
    else:
        out = {"kind": "unknown"}
    out["raw"] = text
    # build full_name
    parts = [out.get("first_name",""), out.get("surname",""), out.get("father","")]
    parts = [title_uz(p) for p in parts if p]
    if parts: out["full_name"] = " ".join(parts)
    return out

import shutil
ROOT = r"D:\CLAUDE\ELEGANT\assets\Teachers Achievements"

results = {}
seen_keys = {}
for tdir, items in qr_data.items():
    print(f"\n=== {tdir} ===", flush=True)
    students = []
    seen = set()
    for it in items:
        for url in it["urls"]:
            fname = url.rsplit("/",1)[-1]
            local = os.path.join(CERT_DIR, fname)
            if not fetch(url, local):
                continue
            data = parse_pdf(local)
            data["source_photo"] = it["file"]
            data["url"] = url
            data["pdf_local"] = "assets/Student Certificates/" + fname
            parts = [data.get("first_name",""), data.get("surname",""), data.get("father","")]
            parts = [" ".join(w.capitalize() for w in p.split()) for p in parts if p]
            if parts: data["full_name"] = " ".join(parts)
            key = (data.get("full_name") or "") + "|" + fname
            if key in seen: continue
            seen.add(key)
            students.append(data)
            n = data.get("full_name","?")
            s = data.get("score") or data.get("level") or data.get("grade") or "?"
            print(f"  {fname[:30]:30s} {n[:40]:40s} {s}", flush=True)

    # also pick up local PDFs in the achievements folder (e.g. raw IELTS PDFs)
    full_ach = os.path.join(ROOT, tdir)
    if os.path.isdir(full_ach):
        for f in sorted(os.listdir(full_ach)):
            if not f.lower().endswith('.pdf'): continue
            src = os.path.join(full_ach, f)
            dst = os.path.join(CERT_DIR, f)
            if not os.path.exists(dst): shutil.copy2(src, dst)
            data = parse_pdf(src)
            data["source_pdf"] = f
            data["pdf_local"] = "assets/Student Certificates/" + f
            parts = [data.get("first_name",""), data.get("surname",""), data.get("father","")]
            parts = [" ".join(w.capitalize() for w in p.split()) for p in parts if p]
            if parts: data["full_name"] = " ".join(parts)
            key = (data.get("full_name") or "") + "|" + f
            if key in seen: continue
            seen.add(key)
            students.append(data)
            n = data.get("full_name","?")
            s = data.get("score") or data.get("level") or data.get("grade") or "?"
            print(f"  +PDF {f[:30]:30s} {n[:40]:40s} {s}", flush=True)
    results[tdir] = students

with open(OUT, 'w', encoding='utf-8') as fp:
    json.dump(results, fp, indent=2, ensure_ascii=False)
print(f"\nWrote {OUT}")

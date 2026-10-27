import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

THAI_TZ = timezone(timedelta(hours=7))

# Paths relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
STUDENT_FILE = SCRIPT_DIR / "Student Name.md"
REPO_FILE = SCRIPT_DIR / "Repo-Lists.md"
OUTPUT_FILE = SCRIPT_DIR / "Readme.md"
OVERRIDES_FILE = SCRIPT_DIR / "PR-Overrides.json"


def format_date(created_at_str: str) -> str:
    """
    Converts ISO 8601 string to 'DD-MM' in Thailand timezone (UTC+7).
    """
    if not created_at_str:
        return ""
    try:
        dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        dt_thai = dt.astimezone(THAI_TZ)
        return dt_thai.strftime("%d-%m")
    except Exception:
        return ""


def parse_students(file_path: Path):
    """
    Parses Student Name.md for Section 1 and Section 2.
    """
    if not file_path.exists():
        print(f"Error: {file_path} not found.")
        return []

    content = file_path.read_text(encoding="utf-8")
    students = []
    current_sec = 1

    for line in content.splitlines():
        line = line.strip()
        if "## Section 1" in line or "# Section 1" in line:
            current_sec = 1
            continue
        elif "## Section 2" in line or "# Section 2" in line:
            current_sec = 2
            continue

        # Match table row: | 1 | 67030002 | นางสาวกชณัช น้อยพันธ์ |
        match = re.match(r"^\|\s*(\d+)\s*\|\s*(\d{8})\s*\|\s*([^|]+)\|", line)
        if match:
            order = int(match.group(1))
            std_id = match.group(2).strip()
            raw_name = match.group(3).strip()
            clean_name = " ".join(raw_name.split())
            name_no_prefix = re.sub(r"^(นาย|นางสาว|น\.ส\.)", "", clean_name).strip()
            first_name = name_no_prefix.split()[0] if name_no_prefix else ""

            students.append(
                {
                    "section": current_sec,
                    "order": order,
                    "id": std_id,
                    "last3": std_id[-3:],
                    "last4": std_id[-4:],
                    "name": clean_name,
                    "first_name": first_name,
                    "submissions": {},  # Populated dynamically by week
                }
            )
    return students


def parse_repos(file_path: Path):
    """
    Parses Repo-Lists.md to get mapping: Week tag -> Repo full name.
    """
    if not file_path.exists():
        print(f"Error: {file_path} not found.")
        return {}

    repos = {}
    content = file_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        # Match table row: | 01 | [Week-01...](https://github.com/IoT-App-2569/Week-01-...) |
        match = re.search(r"\|\s*(\d+)\s*\|\s*\[.*?\]\(https://github\.com/([^)]+)\)", line)
        if match:
            w_num = int(match.group(1))
            w_tag = f"W{w_num:02d}"
            repo_slug = match.group(2).strip().removesuffix(".git")
            repos[w_tag] = repo_slug

    return repos


def load_overrides(file_path: Path):
    """
    Loads manual overrides from PR-Overrides.json.
    """
    if not file_path.exists():
        return {}
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: Failed to load {file_path}: {e}")
        return {}


def fetch_prs_for_repo(repo_slug: str, limit: int = 100):
    """
    Fetches open PRs from a repository using gh CLI.
    """
    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo_slug,
        "--state",
        "open",
        "--limit",
        str(limit),
        "--json",
        "number,title,author,headRefName,url,createdAt",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
        return json.loads(res.stdout)
    except Exception as e:
        print(f"Failed to fetch PRs from {repo_slug}: {e}")
        return []


def identify_students(pr, students):
    """
    Identifies which student(s) the PR belongs to.
    """
    title = pr.get("title", "")
    author_login = pr.get("author", {}).get("login", "")
    ref = pr.get("headRefName", "")

    matched_students = set()
    combined_text = f"{title} {author_login} {ref}"

    # 1. Match full 8-digit student ID (e.g. 67030002 or 6803xxxx)
    found_8digits = re.findall(r"6\d{7}", combined_text)
    for s_id in found_8digits:
        for s in students:
            if s["id"] == s_id:
                matched_students.add(s["id"])

    # 2. Match exact Thai first name (if >= 3 chars)
    for s in students:
        if len(s["first_name"]) >= 3 and s["first_name"] in title:
            matched_students.add(s["id"])

    # 3. Match 3-digit shorthand IDs (e.g. '248', '334', '002', '154')
    found_3digits = re.findall(r"(?<!\d)(\d{3})(?!\d)", combined_text)
    for num3 in found_3digits:
        for s in students:
            if s["last3"] == num3:
                matched_students.add(s["id"])

    # 4. Check author login for student ID or last digits
    found_login_digits = re.findall(r"6\d{7}", author_login)
    for s_id in found_login_digits:
        for s in students:
            if s["id"] == s_id:
                matched_students.add(s["id"])

    return [s for s in students if s["id"] in matched_students]


def generate_markdown(students, week_keys, unmatched_prs, total_prs):
    """
    Generates GitHub flavored Markdown table for Obsidian.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md = []
    md.append(f"# 📊 สรุปการส่งงาน Applications of IoT (IoT-App-2569)\n")
    md.append(f"> 🕒 **อัปเดตล่าสุด:** `{now_str}`  ")
    md.append(f"> 📦 **ประมวลผล:** {total_prs} Pull Requests | ⚠️ **ต้องตรวจทาน:** {len(unmatched_prs)} รายการ  ")
    md.append(f"> 💡 **สัญลักษณ์:** `✅ [PR]` = งานเดี่ยว | `👥 [PR]` = งานกลุ่ม (ส่งเป็นทีม) | `❌` = ยังไม่พบงาน  ")
    md.append(f"> 📅 **วันที่:** ระบุเป็น `วัน-เดือน` (เช่น `04-07`, `15-10`) อยู่ใต้รหัส PR\n")

    # Section 1 & 2
    for sec_num in [1, 2]:
        sec_students = [s for s in students if s["section"] == sec_num]
        md.append(f"## 🏫 Section {sec_num} ({len(sec_students)} คน)\n")

        # Table Header
        header = ["ลำดับ", "รหัส น.ศ.", "ชื่อ-นามสกุล"] + week_keys + ["รวม"]
        aligns = [":---:", "---------", "--------------------------"] + [":---:"] * len(week_keys) + [":---:"]
        md.append("| " + " | ".join(header) + " |")
        md.append("| " + " | ".join(aligns) + " |")

        for s in sec_students:
            row = [str(s["order"]), s["id"], s["name"]]
            done_count = 0
            for w in week_keys:
                subs = s["submissions"].get(w, [])
                if subs:
                    dates = [sub.get("date_str", "") for sub in subs if sub.get("date_str")]
                    unique_dates = sorted(list(set(dates)))

                    if len(unique_dates) == 1:
                        pr_items = []
                        for sub in subs:
                            icon = "👥" if sub.get("is_group", False) else "✅"
                            pr_items.append(f"{icon} [{sub['number']}]({sub['url']})")
                        cell_content = f"{' '.join(pr_items)}<br><small>{unique_dates[0]}</small>"
                    else:
                        pr_items = []
                        for sub in subs:
                            icon = "👥" if sub.get("is_group", False) else "✅"
                            d = f" <small>{sub.get('date_str', '')}</small>" if sub.get("date_str") else ""
                            pr_items.append(f"{icon} [{sub['number']}]({sub['url']}){d}")
                        cell_content = "<br>".join(pr_items)

                    row.append(cell_content)
                    done_count += 1
                else:
                    row.append("❌")
            row.append(f"**{done_count}**")
            md.append("| " + " | ".join(row) + " |")

        md.append("\n")

    # Unmatched Section
    md.append("## ⚠️ รายการที่ต้องตรวจสอบเพิ่มเติม (Unmatched PRs)\n")
    if not unmatched_prs:
        md.append("🎉 *ยอดเยี่ยม! จับคู่งานและรหัสนักศึกษาได้ครบทุกรายการที่ตรวจสอบ*\n")
    else:
        md.append("| สัปดาห์ | PR | วันที่ส่ง | หัวข้อ PR | ผู้ส่ง | สาเหตุที่ต้องตรวจสอบ |")
        md.append("| :---: | :---: | :---: | :--- | :---: | :--- |")
        for item in unmatched_prs:
            pr = item["pr"]
            week = item["week"]
            reason = item["reason"]
            pr_link = f"[#{pr['number']}]({pr['url']})"
            author = pr.get("author", {}).get("login", "")
            title = pr.get("title", "").replace("|", "\\|")
            date_str = format_date(pr.get("createdAt", ""))
            md.append(f"| `{week}` | {pr_link} | `{date_str}` | {title} | `{author}` | {reason} |")
        md.append("\n")

    # Analytics Section
    md.append(generate_analytics(students, week_keys))

    return "\n".join(md)


def generate_analytics(students, week_keys):
    lines = []
    lines.append("\n---\n")
    lines.append("## 📈 สรุปสถิติและวิเคราะห์พฤติกรรมการส่งงาน\n")

    total_stds = len(students)
    sec1 = [s for s in students if s["section"] == 1]
    sec2 = [s for s in students if s["section"] == 2]

    # 1. Weekly Breakdown
    lines.append("### 1. สรุปการส่งงานรายสัปดาห์ (ส่งแล้ว / ยังไม่ส่ง)\n")
    lines.append("| สัปดาห์ | รวมส่ง (คน) | รวมขาด (คน) | % ส่ง | Sec 1 (ส่ง/ขาด) | Sec 2 (ส่ง/ขาด) |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :---: |")

    for w in week_keys:
        s1_done = sum(1 for s in sec1 if s["submissions"].get(w))
        s1_miss = len(sec1) - s1_done
        s2_done = sum(1 for s in sec2 if s["submissions"].get(w))
        s2_miss = len(sec2) - s2_done
        tot_done = s1_done + s2_done
        tot_miss = total_stds - tot_done
        pct = (tot_done / total_stds * 100) if total_stds else 0
        lines.append(f"| **{w}** | **{tot_done}** | {tot_miss} | {pct:.1f}% | {s1_done} / {s1_miss} | {s2_done} / {s2_miss} |")
    lines.append("\n")

    # 2. Complete All Weeks
    complete_students = [s for s in students if all(s["submissions"].get(w) for w in week_keys)]
    lines.append(f"### 2. รายชื่อนักศึกษาที่ส่งครบทุกสัปดาห์ ({len(week_keys)}/{len(week_keys)}) — รวม {len(complete_students)} คน\n")
    lines.append("| ตอนเรียน | ลำดับ | รหัสนักศึกษา | ชื่อ-สกุล |")
    lines.append("| :---: | :---: | :--- | :---: | :--- |")
    for s in complete_students:
        lines.append(f"| Sec {s['section']} | {s['order']} | `{s['id']}` | {s['name']} |")
    lines.append("\n")

    # 3. Behavioral Insights
    lines.append("### 3. วิเคราะห์พฤติกรรมการส่งงาน (Behavioral Insights)\n")

    # 3.1 One-Day Rush (>= 3 weeks on same day)
    lines.append("#### ⚡ กลุ่มที่เร่งส่งวันเดียวหลายงาน (One-Day Rush / Speedrun)")
    lines.append("> นักศึกษาที่มีการส่งงานในวันเดียวกันตั้งแต่ **3 ใบงานขึ้นไป** (สปีดรันช่วงโค้งสุดท้ายของเทอม)\n")
    lines.append("| ตอนเรียน | รหัสนักศึกษา | ชื่อ-สกุล | รวมส่ง | วันที่เร่งส่งและใบงาน |")
    lines.append("| :---: | :---: | :--- | :---: | :--- |")

    for s in students:
        date_map = {}
        for w in week_keys:
            for sub in s["submissions"].get(w, []):
                d = sub.get("date_str")
                if d:
                    date_map.setdefault(d, []).append(w)
        rush_dates = [(d, wks) for d, wks in date_map.items() if len(set(wks)) >= 3]
        if rush_dates:
            rush_dates.sort(key=lambda x: len(set(x[1])), reverse=True)
            desc_items = [f"**{d}** ({len(set(wks))} งาน: {', '.join(sorted(list(set(wks))))})" for d, wks in rush_dates]
            tot_done = sum(1 for w in week_keys if s["submissions"].get(w))
            lines.append(f"| Sec {s['section']} | `{s['id']}` | {s['name']} | **{tot_done}** | {'<br>'.join(desc_items)} |")
    lines.append("\n")

    # 3.2 Out-of-Order Submissions
    lines.append("#### 🔄 กลุ่มที่ทำย้อนไปย้อนมา (Out-of-Order Submissions)")
    lines.append("> นักศึกษาที่ส่งงานสัปดาห์หลังไปก่อน แล้วค่อยย้อนกลับมาส่งงานของสัปดาห์แรกๆ ในภายหลัง\n")
    lines.append("| ตอนเรียน | รหัสนักศึกษา | ชื่อ-สกุล | รวมส่ง | ตัวอย่างการส่งย้อนลำดับ |")
    lines.append("| :---: | :---: | :--- | :---: | :--- |")

    for s in students:
        dated_entries = []
        for idx, w in enumerate(week_keys):
            for sub in s["submissions"].get(w, []):
                d = sub.get("date_str")
                if d and "-" in d:
                    parts = d.split("-")
                    try:
                        sort_key = int(parts[1]) * 100 + int(parts[0])
                        dated_entries.append((idx + 1, sort_key, d, w))
                    except ValueError:
                        pass
        inversions = []
        for i in range(len(dated_entries)):
            for j in range(i + 1, len(dated_entries)):
                w1, k1, d1, tag1 = dated_entries[i]
                w2, k2, d2, tag2 = dated_entries[j]
                if w1 < w2 and k1 > k2:
                    inversions.append(f"{tag2} ({d2}) ส่งก่อน {tag1} ({d1})")

        if len(inversions) >= 2:
            tot_done = sum(1 for w in week_keys if s["submissions"].get(w))
            sample = "<br>".join(inversions[:3])
            if len(inversions) > 3:
                sample += f"<br>*(สลับทั้งหมด {len(inversions)} คู่)*"
            lines.append(f"| Sec {s['section']} | `{s['id']}` | {s['name']} | **{tot_done}** | {sample} |")
    lines.append("\n")

    # 3.3 Consistent Performers
    lines.append("#### 🌟 กลุ่มที่ส่งสม่ำเสมอตลอดเทอม (Consistent & On-Time)")
    lines.append("> นักศึกษาที่ส่งงานกระจายตัวสม่ำเสมอในแต่ละเดือน (ก.ค. - ต.ค.) ไม่ดองงาน และไม่ส่งอัดเกิน 2 งานในวันเดียว\n")
    lines.append("| ตอนเรียน | รหัสนักศึกษา | ชื่อ-สกุล | รวมส่ง | รูปแบบการส่ง |")
    lines.append("| :---: | :---: | :--- | :---: | :--- |")

    for s in students:
        tot_done = sum(1 for w in week_keys if s["submissions"].get(w))
        if tot_done >= 10:
            date_map = {}
            months = set()
            for w in week_keys:
                for sub in s["submissions"].get(w, []):
                    d = sub.get("date_str")
                    if d:
                        date_map.setdefault(d, []).append(w)
                        if "-" in d:
                            months.add(d.split("-")[1])
            max_daily = max(len(set(wks)) for wks in date_map.values()) if date_map else 0
            if len(months) >= 4 and max_daily <= 2:
                lines.append(f"| Sec {s['section']} | `{s['id']}` | {s['name']} | **{tot_done}/{len(week_keys)}** | ส่งกระจายสม่ำเสมอ {len(months)} เดือน (ส่งสูงสุดต่อวัน: {max_daily} งาน) |")
    lines.append("\n")

    return "\n".join(lines)


def main():
    print("========================================================")
    print("      IoT 2569 Homework PR Checklist Synchronizer")
    print("========================================================")
    print("กำลังโหลดรายชื่อนักศึกษา...")
    students = parse_students(STUDENT_FILE)
    if not students:
        print("ไม่พบข้อมูลนักศึกษาใน Student Name.md")
        return
    print(f"โหลดข้อมูลนักศึกษาเรียบร้อย: {len(students)} คน")

    repos = parse_repos(REPO_FILE)
    if not repos:
        print("ไม่พบข้อมูล Repository ใน Repo-Lists.md")
        return
    week_keys = sorted(list(repos.keys()))
    print(f"โหลดรายการ Repositories: {len(repos)} สัปดาห์ ({', '.join(week_keys)})")

    # Initialize submissions dict for all students and weeks
    for s in students:
        s["submissions"] = {w: [] for w in week_keys}

    overrides = load_overrides(OVERRIDES_FILE)
    if overrides:
        print(f"โหลดข้อมูล Manual Overrides: {len(overrides)} รายการ")

    total_prs = 0
    unmatched_prs = []

    for w_tag, repo_slug in repos.items():
        print(f"\n[+] กำลังดึงข้อมูล {w_tag} จาก {repo_slug}...")
        prs = fetch_prs_for_repo(repo_slug, limit=100)
        print(f"    พบ {len(prs)} PRs")
        total_prs += len(prs)

        for pr in prs:
            pr_num = str(pr["number"])
            # Match override by "W01:57" or "57"
            ov_key = f"{w_tag}:{pr_num}" if f"{w_tag}:{pr_num}" in overrides else (pr_num if pr_num in overrides else None)

            if ov_key:
                ov = overrides[ov_key]
                if ov.get("ignore"):
                    continue

                if "students" in ov:
                    ov_students = [str(x) for x in ov["students"]]
                    matched = [s for s in students if s["id"] in ov_students]
                else:
                    matched = identify_students(pr, students)

                weeks = ov.get("weeks", [w_tag])
                is_group = ov.get("is_group", len(matched) > 1)
            else:
                matched = identify_students(pr, students)
                weeks = [w_tag]
                is_group = len(matched) > 1

            if not matched:
                # กรองนักศึกษารุ่นน้อง (รหัส 68xxxxxx) ออกจากการแจ้งเตือน
                combined_info = f"{pr.get('title', '')} {pr.get('author', {}).get('login', '')} {pr.get('headRefName', '')}"
                if re.search(r"68\d{6}", combined_info):
                    continue
                unmatched_prs.append({"week": w_tag, "pr": pr, "reason": "❌ ไม่สามารถระบุรหัสนักศึกษาได้"})
            else:
                author_login = pr.get("author", {}).get("login", "")
                date_str = format_date(pr.get("createdAt", ""))
                for s in matched:
                    is_submitter = (s["id"] in author_login) or (s["last3"] in author_login)
                    for w in weeks:
                        if w in s["submissions"]:
                            if not any(sub["number"] == pr["number"] for sub in s["submissions"][w]):
                                s["submissions"][w].append(
                                    {
                                        "number": pr["number"],
                                        "url": pr["url"],
                                        "title": pr.get("title", ""),
                                        "date_str": date_str,
                                        "is_group": is_group,
                                        "is_submitter": is_submitter,
                                    }
                                )

    print("\nกำลังสร้างตาราง Markdown...")
    output_content = generate_markdown(students, week_keys, unmatched_prs, total_prs)
    OUTPUT_FILE.write_text(output_content, encoding="utf-8")
    print(f"บันทึกผลลงใน {OUTPUT_FILE} เรียบร้อยแล้ว!")
    print(f"สรุป: ประมวลผล {total_prs} PRs | Unmatched: {len(unmatched_prs)} รายการ")


if __name__ == "__main__":
    main()

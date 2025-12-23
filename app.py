import json
import random
from pathlib import Path
from collections import defaultdict

import streamlit as st

# -----------------------
# CONFIG
# -----------------------
APP_TITLE = "General Knowledge Trainer"
BANKS_DIR = Path("data/banks")

WEAK_THRESHOLD = 0.7
WEAK_MAX_TOPICS = 3
DEFAULT_DAILY_PRACTICE_N = 8

DIFFICULTIES = ["easy", "medium", "hard"]
REQUIRED_KEYS = {"id", "topic", "difficulty", "question", "options", "answer", "explanation"}

random.seed()

st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered")
st.title("🧠 General Knowledge Trainer")
st.write(
    "Take a diagnostic exam (1 easy + 1 medium + 1 hard per topic), see your weak areas, "
    "and practice daily with a personalized mix (~70% weak topics, ~30% variety)."
)

# -----------------------
# DATA LOADING (JSONL BANKS)
# -----------------------
@st.cache_data
def load_banks_from_jsonl(banks_dir: Path):
    if not banks_dir.exists():
        st.error(
            f"Missing folder: {banks_dir}\n\n"
            "Create files like data/banks/history.jsonl, data/banks/geography.jsonl, etc."
        )
        st.stop()

    bank_files = sorted(list(banks_dir.glob("*.jsonl")))
    if not bank_files:
        st.error(
            f"No .jsonl files found in {banks_dir}.\n\n"
            "Create at least one bank file, e.g. data/banks/history.jsonl"
        )
        st.stop()

    all_questions = []
    ids_seen = set()
    errors = []

    for fpath in bank_files:
        with fpath.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    q = json.loads(line)
                except Exception as e:
                    errors.append(f"{fpath.name}:{lineno} invalid JSON: {e}")
                    continue

                # Validate keys
                missing = REQUIRED_KEYS - set(q.keys())
                if missing:
                    errors.append(f"{fpath.name}:{lineno} missing keys: {sorted(missing)}")
                    continue

                # Validate types / values
                if q["difficulty"] not in DIFFICULTIES:
                    errors.append(
                        f"{fpath.name}:{lineno} invalid difficulty '{q['difficulty']}'. "
                        f"Must be one of {DIFFICULTIES}."
                    )
                    continue

                if not isinstance(q["options"], list) or len(q["options"]) < 2:
                    errors.append(f"{fpath.name}:{lineno} options must be a list with >= 2 items.")
                    continue

                if q["answer"] not in q["options"]:
                    errors.append(f"{fpath.name}:{lineno} answer must be one of the options.")
                    continue

                if q["id"] in ids_seen:
                    errors.append(f"{fpath.name}:{lineno} duplicate id '{q['id']}'.")
                    continue

                ids_seen.add(q["id"])
                all_questions.append(q)

    if errors:
        st.error("❌ Question bank validation failed. Fix these issues and redeploy:")
        for e in errors[:30]:
            st.write(f"- {e}")
        if len(errors) > 30:
            st.write(f"... and {len(errors) - 30} more.")
        st.stop()

    return all_questions


ALL_QUESTIONS = load_banks_from_jsonl(BANKS_DIR)
TOPICS = sorted({q["topic"] for q in ALL_QUESTIONS})

# Organize by topic/difficulty for sampling
BY_TOPIC_DIFFICULTY = defaultdict(lambda: defaultdict(list))
for q in ALL_QUESTIONS:
    BY_TOPIC_DIFFICULTY[q["topic"]][q["difficulty"]].append(q)

# -----------------------
# PERSONALIZATION
# -----------------------
def init_global_stats():
    return {
        "topic_correct": {t: 0 for t in TOPICS},
        "topic_total": {t: 0 for t in TOPICS},
    }

def record_answer(topic: str, is_correct: bool):
    st.session_state.global_stats["topic_total"][topic] += 1
    if is_correct:
        st.session_state.global_stats["topic_correct"][topic] += 1

def compute_accuracies(stats):
    acc = {}
    for t in TOPICS:
        total = stats["topic_total"].get(t, 0)
        correct = stats["topic_correct"].get(t, 0)
        acc[t] = (correct / total) if total > 0 else 0.5
    return acc

def weakest_topics(stats, threshold=WEAK_THRESHOLD, k=WEAK_MAX_TOPICS):
    acc = compute_accuracies(stats)
    weak = [(t, acc[t]) for t in TOPICS if acc[t] < threshold]
    weak.sort(key=lambda x: x[1])
    return [t for t, _ in weak[:k]]

def personalized_questions(n: int):
    """
    Daily practice:
      ~70% from weakest topics (up to 2–3 topics)
      ~30% from other topics for variety
    """
    stats = st.session_state.global_stats

    if sum(stats["topic_total"].values()) == 0:
        return random.sample(ALL_QUESTIONS, k=min(n, len(ALL_QUESTIONS)))

    weak = weakest_topics(stats, threshold=WEAK_THRESHOLD, k=WEAK_MAX_TOPICS)
    if not weak:
        return random.sample(ALL_QUESTIONS, k=min(n, len(ALL_QUESTIONS)))

    weak_q = [q for q in ALL_QUESTIONS if q["topic"] in weak]
    other_q = [q for q in ALL_QUESTIONS if q["topic"] not in weak]

    n = min(n, len(ALL_QUESTIONS))
    n_weak_target = max(1, int(round(0.7 * n)))

    selected = random.sample(weak_q, k=min(n_weak_target, len(weak_q)))
    remaining = n - len(selected)

    if remaining > 0:
        pool = other_q if other_q else ALL_QUESTIONS
        # avoid duplicates
        pool = [q for q in pool if q not in selected]
        if pool:
            selected += random.sample(pool, k=min(remaining, len(pool)))

    # top up if still short
    if len(selected) < n:
        pool = [q for q in ALL_QUESTIONS if q not in selected]
        if pool:
            selected += random.sample(pool, k=min(n - len(selected), len(pool)))

    random.shuffle(selected)
    return selected

# -----------------------
# DIAGNOSTIC EXAM BUILDER
# -----------------------
def build_diagnostic_exam():
    """
    Exactly 3 questions per topic:
      1 easy + 1 medium + 1 hard
    If a topic is missing a difficulty bucket, it will fall back to any difficulty in that topic.
    """
    exam = []

    for topic in TOPICS:
        picked = []

        for d in DIFFICULTIES:
            candidates = BY_TOPIC_DIFFICULTY[topic].get(d, [])
            if candidates:
                picked.append(random.choice(candidates))

        # If missing any difficulty bucket, top up from all topic questions
        topic_all = []
        for d in DIFFICULTIES:
            topic_all.extend(BY_TOPIC_DIFFICULTY[topic].get(d, []))

        while len(picked) < 3 and topic_all:
            candidate = random.choice(topic_all)
            if candidate not in picked:
                picked.append(candidate)

        exam.extend(picked[:3])

    random.shuffle(exam)
    return exam

# -----------------------
# UI HELPERS
# -----------------------
def render_feedback(feedback):
    if not feedback:
        return
    kind, msg = feedback
    if kind == "success":
        st.success(msg)
    else:
        st.error(msg)

def start_exam_session(kind: str, questions: list):
    """
    kind: "diagnostic" or "practice"
    """
    st.session_state[kind] = {
        "questions": questions,
        "i": 0,
        "score": 0,
        "done": False,
        "answered": False,
        "last_feedback": None,  # ("success"/"error", message)
    }

def show_question_flow(session_key: str, title_prefix: str):
    """
    Two-step flow:
      Submit -> show feedback
      Next -> advance
    """
    sess = st.session_state[session_key]

    if sess["done"]:
        st.success(f"{title_prefix} complete! Score: {sess['score']} / {len(sess['questions'])}")
        return

    q = sess["questions"][sess["i"]]

    # progress
    st.progress(sess["i"] / max(1, len(sess["questions"])))

    st.write(f"**Topic:** {q['topic']} • **Difficulty:** {q['difficulty'].title()}")
    st.subheader(f"Q{sess['i'] + 1}. {q['question']}")

    choice = st.radio(
        "Choose an answer:",
        q["options"],
        key=f"{session_key}_choice_{sess['i']}",
        disabled=sess["answered"]
    )

    render_feedback(sess.get("last_feedback"))

    if not sess["answered"]:
        if st.button("Submit Answer"):
            correct = (choice == q["answer"])
            record_answer(q["topic"], correct)

            if correct:
                sess["score"] += 1
                sess["last_feedback"] = ("success", f"✅ Correct!\n\n**Explanation:** {q['explanation']}")
            else:
                sess["last_feedback"] = ("error", f"❌ Incorrect.\n\n**Correct answer:** {q['answer']}\n\n**Explanation:** {q['explanation']}")

            sess["answered"] = True
            st.rerun()
    else:
        if st.button("Next Question ➡️"):
            sess["i"] += 1
            sess["answered"] = False
            sess["last_feedback"] = None

            if sess["i"] >= len(sess["questions"]):
                sess["done"] = True

            st.rerun()

# -----------------------
# SESSION STATE INIT
# -----------------------
if "global_stats" not in st.session_state:
    st.session_state.global_stats = init_global_stats()

# -----------------------
# SIDEBAR NAV
# -----------------------
st.sidebar.header("Navigation")
page = st.sidebar.radio("Go to:", ["Diagnostic Exam", "Learning Hub", "Daily Practice"])

st.sidebar.markdown("---")
if st.sidebar.button("🧹 Reset all progress"):
    st.session_state.global_stats = init_global_stats()
    st.session_state.pop("diagnostic", None)
    st.session_state.pop("practice", None)
    st.sidebar.success("Progress reset.")
    st.rerun()

# -----------------------
# PAGE: DIAGNOSTIC EXAM
# -----------------------
if page == "Diagnostic Exam":
    st.header("🧪 Diagnostic Exam")
    st.write("Includes **1 easy + 1 medium + 1 hard** question per topic.")

    # Optional: show counts per topic/difficulty
    with st.expander("Show bank coverage (counts per topic/difficulty)"):
        for topic in TOPICS:
            st.write(
                f"**{topic}** — "
                + ", ".join(f"{d}: {len(BY_TOPIC_DIFFICULTY[topic].get(d, []))}" for d in DIFFICULTIES)
            )

    if "diagnostic" not in st.session_state:
        if st.button("Start Diagnostic Exam"):
            start_exam_session("diagnostic", build_diagnostic_exam())
            st.rerun()
    else:
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("🔁 Restart Diagnostic"):
                start_exam_session("diagnostic", build_diagnostic_exam())
                st.rerun()
        with col2:
            st.caption("Flow: Submit → Next Question")

        show_question_flow("diagnostic", "Diagnostic Exam")

        # If finished, guide user to learning hub
        if st.session_state["diagnostic"]["done"]:
            st.info("Next: visit **Learning Hub** to see your weakest topics and start improving.")

# -----------------------
# PAGE: LEARNING HUB
# -----------------------
elif page == "Learning Hub":
    st.header("📚 Learning Hub")

    stats = st.session_state.global_stats
    acc = compute_accuracies(stats)

    if sum(stats["topic_total"].values()) == 0:
        st.info("Take the **Diagnostic Exam** first so I can estimate your strengths and weaknesses.")
    else:
        st.subheader("Your topic accuracy so far")
        for t in TOPICS:
            total = stats["topic_total"][t]
            correct = stats["topic_correct"][t]
            if total > 0:
                st.write(f"- **{t}**: {correct}/{total} ({acc[t]*100:.1f}%)")
            else:
                st.write(f"- **{t}**: no attempts yet")

        weak = weakest_topics(stats, threshold=WEAK_THRESHOLD, k=WEAK_MAX_TOPICS)
        st.markdown("---")
        if weak:
            st.subheader("🎯 Weakest topics (focus these)")
            st.write(", ".join(f"**{t}**" for t in weak))
        else:
            st.subheader("✅ No weak topics detected")
            st.write("You’re doing well — Daily Practice will still mix topics for variety.")

        st.markdown("---")
        st.subheader("Learning module placeholder")
        topic = st.selectbox("Pick a topic to study:", TOPICS)
        st.info(
            "Replace this section with real learning content: short notes, links, videos, flashcards, etc.\n\n"
            f"Selected: **{topic}**"
        )

# -----------------------
# PAGE: DAILY PRACTICE
# -----------------------
elif page == "Daily Practice":
    st.header("📆 Daily Practice (Personalized)")

    stats = st.session_state.global_stats
    if sum(stats["topic_total"].values()) == 0:
        st.info("Take the **Diagnostic Exam** first so I can personalize your daily practice.")
    else:
        weak = weakest_topics(stats, threshold=WEAK_THRESHOLD, k=WEAK_MAX_TOPICS)
        if weak:
            st.write("Today’s practice focuses mostly on:")
            st.write(", ".join(f"**{t}**" for t in weak))
            st.caption("Target mix: ~70% weak topics, ~30% other topics.")
        else:
            st.write("You’re strong across topics — here’s a mixed set for variety.")

        n = st.slider("Number of practice questions:", 3, 15, DEFAULT_DAILY_PRACTICE_N)

        if "practice" not in st.session_state:
            if st.button("Start Practice"):
                start_exam_session("practice", personalized_questions(n))
                st.rerun()
        else:
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("🔁 Restart Practice"):
                    start_exam_session("practice", personalized_questions(n))
                    st.rerun()
            with col2:
                st.caption("Flow: Submit → Next Question")

            show_question_flow("practice", "Daily Practice")




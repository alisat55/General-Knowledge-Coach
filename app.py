import json
import random
from pathlib import Path

import streamlit as st

# -----------------------
# CONFIG
# -----------------------
APP_TITLE = "General Knowledge Trainer"
DATA_PATH = Path("data/questions.json")
DEFAULT_INITIAL_QUIZ_N = 10
DEFAULT_DAILY_PRACTICE_N = 8

st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered")
st.title("🧠 General Knowledge Trainer")
st.write(
    "Take an initial diagnostic quiz, see your weak areas, and practice daily with a personalized mix "
    "(~70% weak topics, ~30% variety)."
)

# -----------------------
# DATA LOADING
# -----------------------
@st.cache_data
def load_questions(path: Path):
    if not path.exists():
        st.error(f"Missing questions file at: {path}")
        st.stop()
    with path.open("r", encoding="utf-8") as f:
        questions = json.load(f)
    # Basic validation
    required = {"question", "options", "answer", "topic"}
    for i, q in enumerate(questions):
        if not required.issubset(q.keys()):
            st.error(f"Question #{i} missing required keys. Needs: {required}")
            st.stop()
        if q["answer"] not in q["options"]:
            st.error(f"Question #{i} answer must be one of the options.")
            st.stop()
    return questions


QUESTIONS = load_questions(DATA_PATH)
TOPICS = sorted({q["topic"] for q in QUESTIONS})

# -----------------------
# PERSONALIZATION
# -----------------------
def compute_accuracies(stats):
    acc = {}
    for t in TOPICS:
        total = stats["topic_total"].get(t, 0)
        correct = stats["topic_correct"].get(t, 0)
        acc[t] = (correct / total) if total > 0 else 0.5
    return acc

def weakest_topics(stats, threshold=0.7, k=3):
    acc = compute_accuracies(stats)
    weak = [(t, acc[t]) for t in TOPICS if acc[t] < threshold]
    weak.sort(key=lambda x: x[1])  # lowest accuracy first
    return [t for t, _ in weak[:k]]

def personalized_questions(n):
    stats = st.session_state.global_stats

    # If no data yet, random mix
    if sum(stats["topic_total"].values()) == 0:
        return random.sample(QUESTIONS, k=min(n, len(QUESTIONS)))

    weak = weakest_topics(stats, threshold=0.7, k=3)
    if not weak:
        return random.sample(QUESTIONS, k=min(n, len(QUESTIONS)))

    weak_q = [q for q in QUESTIONS if q["topic"] in weak]
    other_q = [q for q in QUESTIONS if q["topic"] not in weak]

    n = min(n, len(QUESTIONS))
    n_weak_target = max(1, int(round(0.7 * n)))
    selected = random.sample(weak_q, k=min(n_weak_target, len(weak_q)))

    remaining = n - len(selected)
    if remaining > 0:
        pool = other_q if other_q else QUESTIONS
        selected += random.sample(pool, k=min(remaining, len(pool)))

    # Top up if still short
    if len(selected) < n:
        need = n - len(selected)
        remaining_pool = [q for q in QUESTIONS if q not in selected]
        if remaining_pool:
            selected += random.sample(remaining_pool, k=min(need, len(remaining_pool)))

    random.shuffle(selected)
    return selected

# -----------------------
# SESSION STATE
# -----------------------
def init_global_stats():
    return {
        "topic_correct": {t: 0 for t in TOPICS},
        "topic_total": {t: 0 for t in TOPICS},
    }

if "global_stats" not in st.session_state:
    st.session_state.global_stats = init_global_stats()

def start_initial_quiz(n=DEFAULT_INITIAL_QUIZ_N):
    st.session_state.initial_quiz = {
        "questions": random.sample(QUESTIONS, k=min(n, len(QUESTIONS))),
        "i": 0,
        "score": 0,
        "done": False,
        "answered": False,
        "last_feedback": None
    }

def start_daily_practice(n=DEFAULT_DAILY_PRACTICE_N):
    st.session_state.daily_practice = {
        "questions": personalized_questions(n),
        "i": 0,
        "score": 0,
        "done": False,
        "answered": False,
        "last_feedback": None
    }

def record_answer(topic: str, is_correct: bool):
    st.session_state.global_stats["topic_total"][topic] += 1
    if is_correct:
        st.session_state.global_stats["topic_correct"][topic] += 1

# -----------------------
# SIDEBAR NAV
# -----------------------
st.sidebar.header("Navigation")
page = st.sidebar.radio("Go to:", ["Initial Quiz", "Learning Hub", "Daily Practice"])

st.sidebar.markdown("---")
if st.sidebar.button("🧹 Reset all progress"):
    st.session_state.global_stats = init_global_stats()
    st.session_state.pop("initial_quiz", None)
    st.session_state.pop("daily_practice", None)
    st.sidebar.success("Progress reset.")

# -----------------------
# PAGES
# -----------------------
if page == "Initial Quiz":
    st.header("📋 Initial Diagnostic Quiz")

    n = st.slider("Number of questions:", 5, 20, DEFAULT_INITIAL_QUIZ_N)

    if "initial_quiz" not in st.session_state:
        start_initial_quiz(n)

    if st.button("🔁 Restart Initial Quiz"):
        start_initial_quiz(n)

quiz = st.session_state.initial_quiz

if quiz["done"]:
    st.success(f"Quiz complete! Score: {quiz['score']} / {len(quiz['questions'])}")
    st.info("Go to **Learning Hub** to see weak topics, or **Daily Practice** for personalization.")
else:
    q = quiz["questions"][quiz["i"]]
    st.write(f"**Topic:** {q['topic']}")
    st.subheader(f"Q{quiz['i'] + 1}. {q['question']}")

    # Disable changing after submission (helps UX)
    choice = st.radio(
        "Choose an answer:",
        q["options"],
        key=f"init_choice_{quiz['i']}",
        disabled=quiz["answered"]
    )

    # SHOW FEEDBACK IF ALREADY ANSWERED
    if quiz.get("last_feedback"):
        kind, msg = quiz["last_feedback"]
        if kind == "success":
            st.success(msg)
        else:
            st.error(msg)

    # STEP 1: SUBMIT
    if not quiz["answered"]:
        if st.button("Submit Answer"):
            correct = (choice == q["answer"])
            record_answer(q["topic"], correct)

            if correct:
                quiz["score"] += 1
                quiz["last_feedback"] = ("success", "✅ Correct!")
            else:
                quiz["last_feedback"] = ("error", f"❌ Incorrect. Correct answer: **{q['answer']}**")

            quiz["answered"] = True
            st.rerun()

    # STEP 2: NEXT
    else:
        if st.button("Next Question ➡️"):
            quiz["i"] += 1
            quiz["answered"] = False
            quiz["last_feedback"] = None

            if quiz["i"] >= len(quiz["questions"]):
                quiz["done"] = True

            st.rerun()


elif page == "Learning Hub":
    st.header("📚 Learning Hub")

    stats = st.session_state.global_stats
    acc = compute_accuracies(stats)

    if sum(stats["topic_total"].values()) == 0:
        st.info("Take the **Initial Quiz** first so I can estimate your strengths and weaknesses.")
    else:
        st.subheader("Your topic accuracy so far")
        for t in TOPICS:
            total = stats["topic_total"][t]
            correct = stats["topic_correct"][t]
            if total > 0:
                st.write(f"- **{t}**: {correct}/{total} ({acc[t]*100:.1f}%)")
            else:
                st.write(f"- **{t}**: no attempts yet")

        weak = weakest_topics(stats, threshold=0.7, k=3)
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

prac = st.session_state.daily_practice

if prac["done"]:
    st.success(f"Practice complete! Score: {prac['score']} / {len(prac['questions'])}")
    st.button("Start another session", on_click=start_daily_practice, kwargs={"n": n})
else:
    q = prac["questions"][prac["i"]]
    st.write(f"**Topic:** {q['topic']}")
    st.subheader(f"Q{prac['i'] + 1}. {q['question']}")

    choice = st.radio(
        "Choose an answer:",
        q["options"],
        key=f"prac_choice_{prac['i']}",
        disabled=prac["answered"]
    )

    if prac.get("last_feedback"):
        kind, msg = prac["last_feedback"]
        if kind == "success":
            st.success(msg)
        else:
            st.error(msg)

    if not prac["answered"]:
        if st.button("Submit Practice Answer"):
            correct = (choice == q["answer"])
            record_answer(q["topic"], correct)

            if correct:
                prac["score"] += 1
                prac["last_feedback"] = ("success", "✅ Correct!")
            else:
                prac["last_feedback"] = ("error", f"❌ Incorrect. Correct answer: **{q['answer']}**")

            prac["answered"] = True
            st.rerun()
    else:
        if st.button("Next Question ➡️"):
            prac["i"] += 1
            prac["answered"] = False
            prac["last_feedback"] = None

            if prac["i"] >= len(prac["questions"]):
                prac["done"] = True

            st.rerun()


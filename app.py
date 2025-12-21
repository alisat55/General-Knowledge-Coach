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
WEAK_THRESHOLD = 0.7
WEAK_MAX_TOPICS = 3

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

    required = {"question", "options", "answer", "topic"}
    for i, q in enumerate(questions):
        if not required.issubset(q.keys()):
            st.error(f"Question #{i} missing required keys. Needs: {required}")
            st.stop()
        if not isinstance(q["options"], list) or len(q["options"]) < 2:
            st.error(f"Question #{i} must have an 'options' list with at least 2 items.")
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


def weakest_topics(stats, threshold=WEAK_THRESHOLD, k=WEAK_MAX_TOPICS):
    acc = compute_accuracies(stats)
    weak = [(t, acc[t]) for t in TOPICS if acc[t] < threshold]
    weak.sort(key=lambda x: x[1])  # lowest accuracy first
    return [t for t, _ in weak[:k]]


def personalized_questions(n):
    """
    Daily practice set:
      ~70% from weakest 2–3 topics
      ~30% from other topics (variety)
    """
    stats = st.session_state.global_stats

    # If no data, random mix
    if sum(stats["topic_total"].values()) == 0:
        return random.sample(QUESTIONS, k=min(n, len(QUESTIONS)))

    weak = weakest_topics(stats, threshold=WEAK_THRESHOLD, k=WEAK_MAX_TOPICS)
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
# SESSION STATE HELPERS
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


def start_initial_quiz(n=DEFAULT_INITIAL_QUIZ_N):
    st.session_state.initial_quiz = {
        "questions": random.sample(QUESTIONS, k=min(n, len(QUESTIONS))),
        "i": 0,
        "score": 0,
        "done": False,
        "answered": False,
        "last_feedback": None,  # ("success"/"error", message)
    }


def start_daily_practice(n=DEFAULT_DAILY_PRACTICE_N):
    st.session_state.daily_practice = {
        "questions": personalized_questions(n),
        "i": 0,
        "score": 0,
        "done": False,
        "answered": False,
        "last_feedback": None,  # ("success"/"error", message)
    }


def render_feedback(feedback):
    if not feedback:
        return
    kind, msg = feedback
    if kind == "success":
        st.success(msg)
    else:
        st.error(msg)


if "global_stats" not in st.session_state:
    st.session_state.global_stats = init_global_stats()

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
    st.rerun()

# -----------------------
# PAGE: INITIAL QUIZ
# -----------------------
if page == "Initial Quiz":
    st.header("📋 Initial Diagnostic Quiz")

    n = st.slider("Number of questions:", 5, 20, DEFAULT_INITIAL_QUIZ_N)

    if "initial_quiz" not in st.session_state:
        start_initial_quiz(n)

    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("🔁 Restart Initial Quiz"):
            start_initial_quiz(n)
            st.rerun()
    with colB:
        st.caption("Flow: Submit → Next Question")

    quiz = st.session_state.initial_quiz

    if quiz["done"]:
        st.success(f"Quiz complete! Score: {quiz['score']} / {len(quiz['questions'])}")
        st.info("Go to **Learning Hub** to see weak topics, or **Daily Practice** for personalization.")
    else:
        q = quiz["questions"][quiz["i"]]

        # Progress bar
        st.progress((quiz["i"]) / max(1, len(quiz["questions"])))
        st.write(f"**Topic:** {q['topic']}")
        st.subheader(f"Q{quiz['i'] + 1}. {q['question']}")

        choice = st.radio(
            "Choose an answer:",
            q["options"],
            key=f"init_choice_{quiz['i']}",
            disabled=quiz["answered"]
        )

        # Show feedback if already answered
        render_feedback(quiz.get("last_feedback"))

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
        else:
            if st.button("Next Question ➡️"):
                quiz["i"] += 1
                quiz["answered"] = False
                quiz["last_feedback"] = None

                if quiz["i"] >= len(quiz["questions"]):
                    quiz["done"] = True

                st.rerun()

# -----------------------
# PAGE: LEARNING HUB
# -----------------------
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
        st.info("Take the **Initial Quiz** first so I can personalize your daily practice.")
    else:
        weak = weakest_topics(stats, threshold=WEAK_THRESHOLD, k=WEAK_MAX_TOPICS)
        if weak:
            st.write("Today’s practice focuses mostly on:")
            st.write(", ".join(f"**{t}**" for t in weak))
            st.caption("Target mix: ~70% weak topics, ~30% other topics.")
        else:
            st.write("You’re strong across topics — here’s a mixed set for variety.")

        n = st.slider("Number of practice questions:", 3, 15, DEFAULT_DAILY_PRACTICE_N)

        if "daily_practice" not in st.session_state:
            if st.button("Start Practice"):
                start_daily_practice(n)
                st.rerun()
        else:
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("🔁 Restart Practice"):
                    start_daily_practice(n)
                    st.rerun()
            with col2:
                st.caption("Flow: Submit → Next Question")

        if "daily_practice" in st.session_state:
            prac = st.session_state.daily_practice

            if prac["done"]:
                st.success(f"Practice complete! Score: {prac['score']} / {len(prac['questions'])}")
                if st.button("Start another session"):
                    start_daily_practice(n)
                    st.rerun()
            else:
                q = prac["questions"][prac["i"]]

                st.progress((prac["i"]) / max(1, len(prac["questions"])))
                st.write(f"**Topic:** {q['topic']}")
                st.subheader(f"Q{prac['i'] + 1}. {q['question']}")

                choice = st.radio(
                    "Choose an answer:",
                    q["options"],
                    key=f"prac_choice_{prac['i']}",
                    disabled=prac["answered"]
                )

                # Show feedback if already answered
                render_feedback(prac.get("last_feedback"))

                if not prac["answered"]:
                    if st.button("Submit Answer"):
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



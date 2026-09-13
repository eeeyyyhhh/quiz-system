// static/js/local_storage.js
const LocalDB = {

  _get(key) {
    try {
      return JSON.parse(localStorage.getItem(key) || 'null');
    } catch(e) { return null; }
  },

  _set(key, val) {
    try {
      localStorage.setItem(key, JSON.stringify(val));
    } catch(e) {
      console.warn('localStorage写入失败', e);
    }
  },

  // ==================== 答题记录 ====================

  recordAnswer(q_id, subject, q_type, userAnswer, isCorrect) {
    const answered = this._get('answered_ids') || {};
    answered[q_id] = {
      subject,
      q_type,
      answer: userAnswer,
      correct: isCorrect,
      time: new Date().toISOString().slice(0, 10)
    };
    this._set('answered_ids', answered);

    const today = new Date().toISOString().slice(0, 10);
    const daily = this._get('daily_count') || {};
    if (!daily[today]) daily[today] = 0;
    daily[today]++;
    this._set('daily_count', daily);
  },

  getAnsweredIds(subject) {
    const answered = this._get('answered_ids') || {};
    if (!subject) return new Set(Object.keys(answered));
    return new Set(
      Object.entries(answered)
        .filter(([_, v]) => v.subject === subject)
        .map(([k]) => k)
    );
  },

  isAnswered(q_id) {
    const answered = this._get('answered_ids') || {};
    return !!answered[q_id];
  },

  getTodayCount() {
    const today = new Date().toISOString().slice(0, 10);
    const daily = this._get('daily_count') || {};
    return daily[today] || 0;
  },

  // ==================== 错题本 ====================

  updateWrongBook(q_id, subject, userAnswer, isCorrect) {
    const wrong = this._get('wrong_book') || {};

    if (!isCorrect) {
      if (!wrong[q_id]) {
        wrong[q_id] = {
          subject,
          wrong_count: 1,
          last_answer: userAnswer,
          correct_streak: 0,
          mastered: false,
          next_review: new Date().toISOString().slice(0, 10),
          updated_at: new Date().toISOString()
        };
      } else {
        wrong[q_id].wrong_count++;
        wrong[q_id].last_answer = userAnswer;
        wrong[q_id].correct_streak = 0;
        wrong[q_id].mastered = false;
        wrong[q_id].updated_at = new Date().toISOString();

        const intervals = [1, 2, 4, 7, 15];
        const wc = wrong[q_id].wrong_count;
        const days = intervals[Math.min(wc - 1, intervals.length - 1)];
        const next = new Date();
        next.setDate(next.getDate() + days);
        wrong[q_id].next_review = next.toISOString().slice(0, 10);
      }
    } else {
      if (wrong[q_id] && !wrong[q_id].mastered) {
        wrong[q_id].correct_streak = (wrong[q_id].correct_streak || 0) + 1;
        if (wrong[q_id].correct_streak >= 3) {
          wrong[q_id].mastered = true;
        }
        wrong[q_id].updated_at = new Date().toISOString();
      }
    }
    this._set('wrong_book', wrong);
  },

  getWrongList(subject) {
    const wrong = this._get('wrong_book') || {};
    return Object.entries(wrong)
      .filter(([_, v]) => !v.mastered && (!subject || v.subject === subject))
      .map(([q_id, v]) => ({ q_id, ...v }))
      .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
  },

  getWrongIds(subject) {
    return new Set(this.getWrongList(subject).map(w => w.q_id));
  },

  getWrongCount(subject) {
    return this.getWrongList(subject).length;
  },

  removeWrong(q_id) {
    const wrong = this._get('wrong_book') || {};
    if (wrong[q_id]) {
      wrong[q_id].mastered = true;
      this._set('wrong_book', wrong);
    }
  },

  getTodayReviewIds() {
    const wrong = this._get('wrong_book') || {};
    const today = new Date().toISOString().slice(0, 10);
    return Object.entries(wrong)
      .filter(([_, v]) => !v.mastered && v.next_review <= today)
      .map(([q_id]) => q_id);
  },

  // ==================== 收藏 ====================

  toggleFavorite(q_id, subject) {
    const favs = this._get('favorites') || {};
    if (favs[q_id]) {
      delete favs[q_id];
      this._set('favorites', favs);
      return false;
    } else {
      favs[q_id] = { subject, time: new Date().toISOString() };
      this._set('favorites', favs);
      return true;
    }
  },

  isFavorite(q_id) {
    const favs = this._get('favorites') || {};
    return !!favs[q_id];
  },

  getFavoriteIds(subject) {
    const favs = this._get('favorites') || {};
    return new Set(
      Object.entries(favs)
        .filter(([_, v]) => !subject || v.subject === subject)
        .map(([k]) => k)
    );
  },

  getFavoriteCount(subject) {
    return this.getFavoriteIds(subject).size;
  },

  // ==================== 统计 ====================

  getStats(subject) {
    const answered = this._get('answered_ids') || {};
    const entries = Object.entries(answered)
      .filter(([_, v]) => !subject || v.subject === subject);

    const answeredCount = entries.length;
    const correctCount  = entries.filter(([_, v]) => v.correct).length;
    const wrongCount    = this.getWrongCount(subject);
    const favCount      = this.getFavoriteIds(subject).size;

    return {
      answered:     answeredCount,
      correct:      correctCount,
      wrong:        wrongCount,
      favorites:    favCount,
      correct_rate: answeredCount > 0
        ? Math.round(correctCount / answeredCount * 100) : 0
    };
  },

  getWeekData() {
    const daily = this._get('daily_count') || {};
    const result = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const key = d.toISOString().slice(0, 10);
      result.push({
        date:  key.slice(5),
        count: daily[key] || 0
      });
    }
    return result;
  },

  clearAll() {
    localStorage.removeItem('answered_ids');
    localStorage.removeItem('wrong_book');
    localStorage.removeItem('favorites');
    localStorage.removeItem('daily_count');
  }
};
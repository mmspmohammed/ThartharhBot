from datetime import date, datetime

SIGNS = {
    "en": ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
           "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"],
    "ar": ["الحمل", "الثور", "الجوزاء", "السرطان", "الأسد", "العذراء",
           "الميزان", "العقرب", "القوس", "الجدي", "الدلو", "الحوت"],
}

def zodiac_index(m, d):
    if (m == 3 and d >= 21) or (m == 4 and d <= 19): return 0
    if (m == 4 and d >= 20) or (m == 5 and d <= 20): return 1
    if (m == 5 and d >= 21) or (m == 6 and d <= 20): return 2
    if (m == 6 and d >= 21) or (m == 7 and d <= 22): return 3
    if (m == 7 and d >= 23) or (m == 8 and d <= 22): return 4
    if (m == 8 and d >= 23) or (m == 9 and d <= 22): return 5
    if (m == 9 and d >= 23) or (m == 10 and d <= 22): return 6
    if (m == 10 and d >= 23) or (m == 11 and d <= 21): return 7
    if (m == 11 and d >= 22) or (m == 12 and d <= 21): return 8
    if (m == 12 and d >= 22) or (m == 1 and d <= 19): return 9
    if (m == 1 and d >= 20) or (m == 2 and d <= 18): return 10
    return 11

def zodiac_of(d, lang="ar"):
    return SIGNS.get(lang, SIGNS["ar"])[zodiac_index(d.month, d.day)]

def age_of(born, today=None):
    today = today or date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

def join_duration(joined_at, lang="ar"):
    """مدة العضوية: بالأيام إذا أقل من شهر، وبالسنوات والشهور بعدها."""
    dt = datetime.fromisoformat(joined_at)
    now = datetime.now()
    months = (now.year - dt.year) * 12 + (now.month - dt.month)
    if now.day < dt.day:
        months -= 1
    if months < 1:
        days = max(1, (now - dt).days)
        return f"{days} يوم" if lang == "ar" else f"{days} days"
    years, rem = divmod(months, 12)
    if years == 0:
        return f"{months} شهر" if lang == "ar" else f"{months} months"
    if lang == "ar":
        return f"{years} سنة و {rem} شهر"
    return f"{years} years, {rem} months"

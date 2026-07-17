import sqlite3
conn = sqlite3.connect('data/aerie.db')
cur = conn.cursor()
print('=== ALL TABLES ===')
for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print(row[0])
print()
print('=== cognition_log recent 5 ===')
for row in cur.execute('SELECT id, user_message, source FROM cognition_log ORDER BY id DESC LIMIT 5'):
    print(f'id={row[0]:3d} src={row[2]:10s} text={row[1][:80]!r}')
print()
print('=== emotion_state_snapshot recent 8 ===')
for row in cur.execute('SELECT id, ts, pleasure, arousal, dominance, label, trigger_event FROM emotion_state_snapshot ORDER BY id DESC LIMIT 8'):
    print(f'id={row[0]:3d} ts={row[1]} P={row[2]} A={row[3]} D={row[4]} label={row[5]!r} trig={row[6]!r}')
print()
print('=== emotion_state_snapshot by user_id ===')
for row in cur.execute('SELECT user_id, COUNT(*) FROM emotion_state_snapshot GROUP BY user_id'):
    print(f'user_id={row[0]}: {row[1]}')
print()
print('=== sample chat_messages (find correct table) ===')
for tbl in ['chat_message', 'chat_log', 'messages', 'message_log']:
    try:
        cnt = cur.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()
        if cnt:
            print(f'{tbl}: {cnt[0]} rows')
    except Exception:
        pass

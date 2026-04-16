from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__, static_folder=".")
app.secret_key = os.getenv("SECRET_KEY", "wabot-secret-2025")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///wabot.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ─── Modelos ──────────────────────────────────────────────────────────────────

class FAQ(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(300), nullable=False)
    keywords = db.Column(db.String(500), default="")
    answer   = db.Column(db.Text, nullable=False)
    created  = db.Column(db.DateTime, default=datetime.utcnow)

class Config(db.Model):
    id    = db.Column(db.Integer, primary_key=True)
    key   = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, default="")

class MessageLog(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    sender    = db.Column(db.String(100))
    message   = db.Column(db.Text)
    response  = db.Column(db.Text)
    matched   = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_cfg(key, default=""):
    row = Config.query.filter_by(key=key).first()
    return row.value if row else default

def set_cfg(key, value):
    row = Config.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(Config(key=key, value=value))
    db.session.commit()

def find_answer(text: str):
    text_lower = text.lower()
    for faq in FAQ.query.all():
        keywords = [k.strip().lower() for k in faq.keywords.split(",") if k.strip()]
        if any(kw in text_lower for kw in keywords):
            return faq.answer, faq.id
        snippet = faq.question.lower().replace("¿","").replace("?","")[:20]
        if snippet and snippet in text_lower:
            return faq.answer, faq.id
    return None, None

def seed():
    if not FAQ.query.first():
        samples = [
            FAQ(question="¿Cuál es el horario de atención?",
                keywords="horario,abierto,abrir,cierre,hora",
                answer="Estamos abiertos de lunes a viernes de 9:00 a 18:00 h y sábados de 10:00 a 14:00 h."),
            FAQ(question="¿Cómo hago un pedido?",
                keywords="pedido,comprar,encargar,pedir,compra",
                answer="Puedes hacer tu pedido directamente por WhatsApp, en nuestra web o visitándonos en tienda física. 😊"),
            FAQ(question="¿Cuánto tarda el envío?",
                keywords="envío,entrega,días,plazo,llega,shipping",
                answer="Envíos nacionales: 2-3 días laborables. Internacionales: 5-7 días."),
            FAQ(question="¿Cuáles son los métodos de pago?",
                keywords="pago,pagar,tarjeta,transferencia,bizum,efectivo",
                answer="Aceptamos tarjeta de crédito/débito, Bizum, transferencia bancaria y efectivo en tienda."),
        ]
        db.session.bulk_save_objects(samples)
    defaults = {
        "business_name": "WA·BOT",
        "welcome_msg": "¡Hola! 👋 Soy el asistente de WA·BOT. ¿En qué puedo ayudarte?",
        "fallback_msg": "Lo siento, no tengo respuesta para eso. Un agente te contactará pronto. 🙏",
        "phone": "+34 612 345 678",
    }
    for k, v in defaults.items():
        if not Config.query.filter_by(key=k).first():
            db.session.add(Config(key=k, value=v))
    db.session.commit()

# ─── Páginas HTML ─────────────────────────────────────────────────────────────

@app.route("/")
def landing():
    return send_from_directory(".", "index.html")

@app.route("/admin")
def admin():
    return send_from_directory(".", "admin.html")

# ─── API: FAQs ────────────────────────────────────────────────────────────────

@app.route("/api/faqs", methods=["GET"])
def list_faqs():
    return jsonify([
        {"id": f.id, "question": f.question, "keywords": f.keywords, "answer": f.answer}
        for f in FAQ.query.order_by(FAQ.created).all()
    ])

@app.route("/api/faqs", methods=["POST"])
def create_faq():
    d = request.get_json()
    faq = FAQ(question=d["question"], keywords=d.get("keywords", ""), answer=d["answer"])
    db.session.add(faq)
    db.session.commit()
    return jsonify({"id": faq.id}), 201

@app.route("/api/faqs/<int:fid>", methods=["PUT"])
def update_faq(fid):
    faq = FAQ.query.get_or_404(fid)
    d = request.get_json()
    faq.question = d.get("question", faq.question)
    faq.keywords = d.get("keywords", faq.keywords)
    faq.answer   = d.get("answer", faq.answer)
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/api/faqs/<int:fid>", methods=["DELETE"])
def delete_faq(fid):
    db.session.delete(FAQ.query.get_or_404(fid))
    db.session.commit()
    return jsonify({"ok": True})

# ─── API: Config ──────────────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify({row.key: row.value for row in Config.query.all()})

@app.route("/api/config", methods=["POST"])
def save_config():
    for k, v in request.get_json().items():
        set_cfg(k, v)
    return jsonify({"ok": True})

# ─── API: Chat ────────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def chat():
    d = request.get_json()
    msg    = d.get("message", "").strip()
    sender = d.get("sender", "user")
    if not msg:
        return jsonify({"error": "empty"}), 400
    answer, faq_id = find_answer(msg)
    matched  = answer is not None
    response = answer or get_cfg("fallback_msg", "Lo siento, un agente te contactará pronto.")
    db.session.add(MessageLog(sender=sender, message=msg, response=response, matched=matched))
    db.session.commit()
    return jsonify({"response": response, "matched": matched, "faq_id": faq_id})

# ─── API: Logs ────────────────────────────────────────────────────────────────

@app.route("/api/logs", methods=["GET"])
def get_logs():
    logs = MessageLog.query.order_by(MessageLog.timestamp.desc()).limit(100).all()
    return jsonify([{
        "id": l.id,
        "sender": l.sender,
        "message": l.message,
        "response": l.response,
        "matched": l.matched,
        "timestamp": l.timestamp.isoformat()
    } for l in logs])

# ─── API: Stats ───────────────────────────────────────────────────────────────

@app.route("/api/stats", methods=["GET"])
def stats():
    total   = MessageLog.query.count()
    matched = MessageLog.query.filter_by(matched=True).count()
    return jsonify({
        "total_messages": total,
        "matched":        matched,
        "unmatched":      total - matched,
        "hit_rate":       round(matched / total * 100, 1) if total else 0,
        "total_faqs":     FAQ.query.count(),
    })

# ─── Webhook WhatsApp (Twilio TwiML) ─────────────────────────────────────────

@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    from_number = request.form.get("From", "unknown")
    body        = request.form.get("Body", "").strip()
    if not body:
        return "", 204
    answer, _ = find_answer(body)
    matched   = answer is not None
    response  = answer or get_cfg("fallback_msg")
    db.session.add(MessageLog(sender=from_number, message=body, response=response, matched=matched))
    db.session.commit()
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Message>{response}</Message></Response>"""
    return twiml, 200, {"Content-Type": "text/xml"}

# ─── Init ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed()
    print("\n  WA·BOT corriendo en http://localhost:5000")
    print("  Landing:  http://localhost:5000/")
    print("  Admin:    http://localhost:5000/admin\n")
    app.run(debug=True, port=5000)

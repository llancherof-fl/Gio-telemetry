"""
GIO Telemetry — Admin Endpoints (Hidden)
Protected by ADMIN_SECRET header. Provides flush operations
with preview, confirmation, and audit logging.
"""
import datetime

from flask import Blueprint, jsonify, request, render_template_string

from app.config import Config
from app.database import count_records_for_flush, flush_data, count_total

admin_bp = Blueprint('admin', __name__)


# ══════════════════════════════════════════
#  AUTH HELPER
# ══════════════════════════════════════════

def _check_secret():
    """Validate the admin secret. Returns error response or None if valid."""
    if not Config.ADMIN_SECRET:
        return jsonify({
            'error': 'ADMIN_SECRET no esta configurado en el servidor. Agrega ADMIN_SECRET al .env',
        }), 503

    provided = request.headers.get('X-Admin-Secret', '')
    if provided != Config.ADMIN_SECRET:
        return jsonify({'error': 'Secreto invalido'}), 401

    return None


# ══════════════════════════════════════════
#  FLUSH PREVIEW (non-destructive)
# ══════════════════════════════════════════

@admin_bp.route('/api/admin/flush-preview', methods=['POST'])
def flush_preview():
    """Preview how many records would be deleted — no data is modified."""
    auth_error = _check_secret()
    if auth_error:
        return auth_error

    body = request.get_json(silent=True) or {}
    mode = body.get('mode', '')

    if mode not in ('all', 'range', 'older_than'):
        return jsonify({'error': 'Modo invalido. Usa: all, range, older_than'}), 400

    try:
        start_dt, end_dt, days = _parse_flush_params(mode, body)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    count = count_records_for_flush(mode, start=start_dt, end=end_dt, days=days)
    total = count_total()

    descriptions = {
        'all': 'Todos los registros',
        'range': f'Registros del {start_dt} al {end_dt}' if start_dt else '',
        'older_than': f'Registros con mas de {days} dias de antiguedad' if days else '',
    }

    return jsonify({
        'count': count,
        'total': total,
        'remaining': total - count,
        'mode': mode,
        'description': descriptions.get(mode, ''),
    })


# ══════════════════════════════════════════
#  FLUSH EXECUTE (destructive)
# ══════════════════════════════════════════

@admin_bp.route('/api/admin/flush', methods=['DELETE'])
def flush_execute():
    """Delete records. Requires confirmation text 'ELIMINAR'."""
    auth_error = _check_secret()
    if auth_error:
        return auth_error

    body = request.get_json(silent=True) or {}
    mode = body.get('mode', '')
    confirm = body.get('confirm', '')

    # Double confirmation
    if confirm != 'ELIMINAR':
        return jsonify({
            'error': 'Debes enviar confirm: "ELIMINAR" para ejecutar el flush',
        }), 400

    if mode not in ('all', 'range', 'older_than'):
        return jsonify({'error': 'Modo invalido. Usa: all, range, older_than'}), 400

    try:
        start_dt, end_dt, days = _parse_flush_params(mode, body)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    # Execute
    deleted = flush_data(mode, start=start_dt, end=end_dt, days=days)
    remaining = count_total()

    # Audit log
    client_ip = request.remote_addr or 'unknown'
    print(f"[FLUSH] {datetime.datetime.now().isoformat()} | IP: {client_ip} | "
          f"mode={mode} | deleted={deleted} | remaining={remaining}")

    return jsonify({
        'deleted': deleted,
        'remaining': remaining,
        'mode': mode,
    })


# ══════════════════════════════════════════
#  ADMIN UI (hidden page)
# ══════════════════════════════════════════

@admin_bp.route('/admin')
def admin_page():
    """Hidden admin page for database management."""
    return render_template_string(ADMIN_HTML, ec2_name=Config.EC2_NAME)


# ══════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════

def _parse_flush_params(mode, body):
    """Parse and validate flush parameters. Returns (start_dt, end_dt, days)."""
    start_dt = None
    end_dt = None
    days = None

    if mode == 'range':
        start_str = body.get('start', '')
        end_str = body.get('end', '')
        if not start_str or not end_str:
            raise ValueError('Se requieren start y end para modo range')
        try:
            start_dt = datetime.datetime.fromisoformat(start_str)
            end_dt = datetime.datetime.fromisoformat(end_str)
        except (ValueError, TypeError):
            raise ValueError('Formato de fecha invalido')
        if start_dt >= end_dt:
            raise ValueError('start debe ser anterior a end')

    elif mode == 'older_than':
        days = body.get('days')
        if days is None:
            raise ValueError('Se requiere days para modo older_than')
        try:
            days = int(days)
            if days < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('days debe ser un numero entero positivo')

    return start_dt, end_dt, days


# ══════════════════════════════════════════
#  ADMIN HTML TEMPLATE
# ══════════════════════════════════════════

ADMIN_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin · GIO Telemetry</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&family=Roboto+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg:#0a0e1a; --bg-card:#0f1525; --bg-input:#111827;
            --border:#1e2a4a; --border-hover:#2d3f6e;
            --blue:#4dabf7; --blue-dim:rgba(77,171,247,0.12);
            --green:#51cf66; --green-dim:rgba(81,207,102,0.12);
            --red:#ff6b6b; --red-dim:rgba(255,107,107,0.12);
            --orange:#ffa94d; --orange-dim:rgba(255,169,77,0.12);
            --text:#e1e8f5; --text-sec:#8da0c2; --text-muted:#4a5e85;
            --radius:10px;
        }
        *,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
        body{font-family:'Roboto',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
        .admin-container{width:100%;max-width:520px}
        .admin-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:28px;margin-bottom:16px}
        h1{font-size:1.1rem;font-weight:700;margin-bottom:6px;display:flex;align-items:center;gap:8px}
        .subtitle{font-size:0.75rem;color:var(--text-muted);margin-bottom:22px}
        .field{margin-bottom:16px}
        .field label{display:block;font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;font-weight:500;margin-bottom:6px}
        .field input,.field select{width:100%;background:var(--bg-input);border:1px solid var(--border);border-radius:8px;padding:10px 14px;color:var(--text);font-family:'Roboto',sans-serif;font-size:0.85rem;outline:none;transition:border-color 0.2s}
        .field input:focus,.field select:focus{border-color:var(--blue)}
        .field input::-webkit-calendar-picker-indicator{filter:invert(0.6) sepia(0.2) hue-rotate(190deg)}
        .radio-group{display:flex;gap:8px;flex-wrap:wrap}
        .radio-btn{padding:8px 16px;border-radius:8px;border:1px solid var(--border);background:var(--bg-input);color:var(--text-muted);font-size:0.78rem;font-weight:500;cursor:pointer;transition:all 0.2s}
        .radio-btn.active{border-color:var(--blue);color:var(--blue);background:var(--blue-dim)}
        .radio-btn:hover:not(.active){border-color:var(--border-hover);color:var(--text-sec)}
        .date-fields{display:none;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}
        .date-fields.show{display:grid}
        .days-field{display:none;margin-top:12px}
        .days-field.show{display:block}
        .preview-box{background:var(--bg-input);border:1px solid var(--border);border-radius:8px;padding:14px 16px;margin:16px 0;font-size:0.82rem;display:none}
        .preview-box.show{display:block}
        .preview-count{font-family:'Roboto Mono',monospace;font-size:1.3rem;font-weight:700;color:var(--orange)}
        .preview-detail{color:var(--text-muted);font-size:0.75rem;margin-top:4px}
        .btn{padding:10px 20px;border-radius:8px;border:none;font-family:'Roboto',sans-serif;font-size:0.82rem;font-weight:500;cursor:pointer;transition:all 0.2s;display:inline-flex;align-items:center;gap:6px;width:100%;justify-content:center}
        .btn-blue{background:rgba(77,171,247,0.15);color:var(--blue);border:1px solid rgba(77,171,247,0.3)}
        .btn-blue:hover{background:rgba(77,171,247,0.25)}
        .btn-red{background:var(--red-dim);color:var(--red);border:1px solid rgba(255,107,107,0.3)}
        .btn-red:hover{background:rgba(255,107,107,0.25)}
        .btn:disabled{opacity:0.3;cursor:not-allowed}
        .confirm-section{display:none;margin-top:16px;padding-top:16px;border-top:1px solid var(--border)}
        .confirm-section.show{display:block}
        .warning{font-size:0.72rem;color:var(--red);margin-bottom:10px;display:flex;align-items:center;gap:6px}
        .actions{display:flex;gap:10px;margin-top:12px}
        .toast{position:fixed;bottom:20px;right:20px;background:var(--bg-card);border:1px solid var(--border-hover);border-radius:var(--radius);padding:12px 20px;font-size:0.8rem;z-index:10001;transform:translateY(80px);opacity:0;transition:all 0.3s;box-shadow:0 8px 30px rgba(0,0,0,0.5)}
        .toast.show{transform:translateY(0);opacity:1}
        .toast.success{border-color:var(--green);color:var(--green)}
        .toast.error{border-color:var(--red);color:var(--red)}
        .back-link{font-size:0.75rem;color:var(--text-muted);text-decoration:none;display:inline-flex;align-items:center;gap:4px;margin-bottom:16px;transition:color 0.2s}
        .back-link:hover{color:var(--blue)}
        .badge{padding:2px 8px;border-radius:5px;font-size:0.65rem;font-weight:700;font-family:'Roboto Mono',monospace;letter-spacing:0.04em;text-transform:uppercase;background:var(--red-dim);color:var(--red);border:1px solid rgba(255,107,107,0.2)}
    </style>
</head>
<body>
<div class="admin-container">
    <a href="/" class="back-link">← Volver al Dashboard</a>

    <!-- AUTH -->
    <div class="admin-card" id="auth-card">
        <h1>🔐 Admin · GIO Telemetry</h1>
        <p class="subtitle">{{ ec2_name }} — Ingresa el secreto de administración</p>
        <div class="field">
            <label>Admin Secret</label>
            <input type="password" id="secret-input" placeholder="Ingresa el secreto..." autocomplete="off">
        </div>
        <button class="btn btn-blue" onclick="authenticate()">Ingresar</button>
    </div>

    <!-- FLUSH PANEL (hidden until authenticated) -->
    <div class="admin-card" id="flush-card" style="display:none">
        <h1><span class="badge">ADMIN</span> Limpieza de Base de Datos</h1>
        <p class="subtitle">{{ ec2_name }} — Base de datos compartida entre todas las instancias</p>

        <div class="field">
            <label>Modo de limpieza</label>
            <div class="radio-group">
                <div class="radio-btn active" onclick="setMode('all')">🗑️ Total</div>
                <div class="radio-btn" onclick="setMode('range')">📅 Rango</div>
                <div class="radio-btn" onclick="setMode('older_than')">⏳ Antiguos</div>
            </div>
        </div>

        <div class="date-fields" id="date-fields">
            <div class="field">
                <label>Desde</label>
                <input type="datetime-local" id="flush-start">
            </div>
            <div class="field">
                <label>Hasta</label>
                <input type="datetime-local" id="flush-end">
            </div>
        </div>

        <div class="days-field" id="days-field">
            <div class="field">
                <label>Eliminar registros con más de N días</label>
                <input type="number" id="flush-days" min="1" value="30" placeholder="30">
            </div>
        </div>

        <button class="btn btn-blue" onclick="preview()" id="btn-preview">Vista Previa</button>

        <div class="preview-box" id="preview-box">
            <div>Se eliminarán:</div>
            <div class="preview-count" id="preview-count">0</div>
            <div class="preview-detail" id="preview-detail"></div>
        </div>

        <div class="confirm-section" id="confirm-section">
            <div class="warning">⚠️ Esta acción es irreversible y afecta a TODAS las instancias</div>
            <div class="field">
                <label>Escribe ELIMINAR para confirmar</label>
                <input type="text" id="confirm-input" placeholder="ELIMINAR" oninput="checkConfirm()" autocomplete="off">
            </div>
            <div class="actions">
                <button class="btn btn-red" id="btn-flush" disabled onclick="executeFlush()">🗑️ Ejecutar Flush</button>
            </div>
        </div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
var adminSecret='';
var currentMode='all';

function authenticate(){
    adminSecret=document.getElementById('secret-input').value.trim();
    if(!adminSecret){showToast('Ingresa el secreto','error');return}
    // Test the secret with a preview
    fetch('/api/admin/flush-preview',{
        method:'POST',
        headers:{'Content-Type':'application/json','X-Admin-Secret':adminSecret},
        body:JSON.stringify({mode:'all'})
    }).then(function(r){
        if(r.status===401){showToast('Secreto invalido','error');return}
        if(r.status===503){showToast('ADMIN_SECRET no configurado en el servidor','error');return}
        return r.json()
    }).then(function(data){
        if(!data) return;
        document.getElementById('auth-card').style.display='none';
        document.getElementById('flush-card').style.display='block';
        showToast('Autenticado correctamente','success');
    }).catch(function(){showToast('Error de conexion','error')});
}

function setMode(mode){
    currentMode=mode;
    document.querySelectorAll('.radio-btn').forEach(function(b){b.classList.remove('active')});
    event.target.classList.add('active');
    document.getElementById('date-fields').classList.toggle('show',mode==='range');
    document.getElementById('days-field').classList.toggle('show',mode==='older_than');
    document.getElementById('preview-box').classList.remove('show');
    document.getElementById('confirm-section').classList.remove('show');
}

function preview(){
    var body={mode:currentMode};
    if(currentMode==='range'){
        body.start=document.getElementById('flush-start').value;
        body.end=document.getElementById('flush-end').value;
        if(!body.start||!body.end){showToast('Selecciona las fechas','error');return}
    }
    if(currentMode==='older_than'){
        body.days=parseInt(document.getElementById('flush-days').value);
        if(!body.days||body.days<1){showToast('Ingresa un numero de dias valido','error');return}
    }
    document.getElementById('btn-preview').textContent='Calculando...';
    fetch('/api/admin/flush-preview',{
        method:'POST',
        headers:{'Content-Type':'application/json','X-Admin-Secret':adminSecret},
        body:JSON.stringify(body)
    }).then(function(r){return r.json()}).then(function(data){
        document.getElementById('btn-preview').textContent='Vista Previa';
        if(data.error){showToast(data.error,'error');return}
        document.getElementById('preview-count').textContent=data.count.toLocaleString()+' registros';
        document.getElementById('preview-detail').textContent=data.description+' — Quedarán '+data.remaining.toLocaleString()+' registros';
        document.getElementById('preview-box').classList.add('show');
        if(data.count>0){
            document.getElementById('confirm-section').classList.add('show');
        }else{
            document.getElementById('confirm-section').classList.remove('show');
            showToast('No hay registros para eliminar','error');
        }
    }).catch(function(){
        document.getElementById('btn-preview').textContent='Vista Previa';
        showToast('Error al consultar','error');
    });
}

function checkConfirm(){
    var val=document.getElementById('confirm-input').value;
    document.getElementById('btn-flush').disabled=(val!=='ELIMINAR');
}

function executeFlush(){
    var body={mode:currentMode,confirm:'ELIMINAR'};
    if(currentMode==='range'){
        body.start=document.getElementById('flush-start').value;
        body.end=document.getElementById('flush-end').value;
    }
    if(currentMode==='older_than'){
        body.days=parseInt(document.getElementById('flush-days').value);
    }
    document.getElementById('btn-flush').textContent='Eliminando...';
    document.getElementById('btn-flush').disabled=true;
    fetch('/api/admin/flush',{
        method:'DELETE',
        headers:{'Content-Type':'application/json','X-Admin-Secret':adminSecret},
        body:JSON.stringify(body)
    }).then(function(r){return r.json()}).then(function(data){
        document.getElementById('btn-flush').textContent='🗑️ Ejecutar Flush';
        if(data.error){showToast(data.error,'error');return}
        showToast('✓ '+data.deleted+' registros eliminados. Quedan '+data.remaining,'success');
        document.getElementById('confirm-section').classList.remove('show');
        document.getElementById('preview-box').classList.remove('show');
        document.getElementById('confirm-input').value='';
    }).catch(function(){
        document.getElementById('btn-flush').textContent='🗑️ Ejecutar Flush';
        showToast('Error al ejecutar flush','error');
    });
}

function showToast(msg,type){
    var t=document.getElementById('toast');
    t.textContent=msg;
    t.className='toast '+(type||'')+' show';
    setTimeout(function(){t.classList.remove('show')},3500);
}

// Enter key on secret input
document.getElementById('secret-input').addEventListener('keydown',function(e){
    if(e.key==='Enter') authenticate();
});
</script>
</body>
</html>"""

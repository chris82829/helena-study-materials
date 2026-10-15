"""Password-protected survey administration; opaque cookies plus CSRF protection."""
import hashlib
import re
import secrets
import threading
import time
from functools import wraps

from flask import Blueprint, jsonify, request, make_response
from werkzeug.security import check_password_hash

from pydantic import ValidationError
from admin_store import AdminSurveyData, AdminAnswerCorrection
from survey_store import SURVEY_DEFINITION, SurveyConflict
from survey_analytics import analytics
from telemetry_analytics import telemetry_analysis, telemetry_participant_csv
from system_prompt_store import PromptConflict


def register_admin(app, surveys, privacy, releases, sessions, notice, system_prompts):
    bp=Blueprint('survey_admin',__name__,url_prefix='/api/admin')
    data=AdminSurveyData(surveys,privacy,releases,sessions)
    app.extensions['admin_data']=data
    lock=threading.Lock();logins={};attempts={}
    cookie='helena_admin';lifetime=8*60*60
    def error(message,status):return jsonify(error={'message':message}),status
    def active():
        digest=hashlib.sha256(request.cookies.get(cookie,'').encode()).hexdigest()
        with lock:
            now=time.monotonic()
            for key in list(logins):
                if logins[key]['expires']<=now:del logins[key]
            return logins.get(digest)
    def protected(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            session=active()
            if not session:return error('Bitte melde dich an.',401)
            if request.method not in ('GET','HEAD') and not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf']):
                return error('Die Sicherheitsbestätigung fehlt. Bitte neu anmelden.',403)
            return fn(*args,**kwargs)
        return wrapped
    @bp.get('/session')
    def status():
        session=active()
        return jsonify(configured=bool(app.config['ADMIN_PASSWORD_HASH']),authenticated=bool(session),csrf=session['csrf'] if session else None)
    @bp.post('/login')
    def login():
        password_hash=app.config['ADMIN_PASSWORD_HASH']
        if not password_hash:return error('Der Verwaltungszugang ist noch nicht eingerichtet.',503)
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={'password'} or not isinstance(body['password'],str) or not 1<=len(body['password'])<=200:
            return error('Bitte das Passwort eingeben.',400)
        key=request.remote_addr or 'unknown';now=time.monotonic()
        with lock:
            for old in list(attempts):
                if attempts[old]['until']<now:del attempts[old]
            rate=attempts.setdefault(key,{'count':0,'until':now+600})
            if rate['count']>=5:return error('Zu viele Versuche. Bitte in zehn Minuten erneut versuchen.',429)
            if len(attempts)>1000:return error('Bitte später erneut versuchen.',429)
            rate['count']+=1
        if not check_password_hash(password_hash,body['password']):return error('Passwort nicht korrekt.',401)
        raw=secrets.token_hex(32);csrf=secrets.token_hex(32)
        with lock:
            attempts.pop(key,None)
            if len(logins)>=100:logins.clear()
            logins[hashlib.sha256(raw.encode()).hexdigest()]={'csrf':csrf,'expires':time.monotonic()+lifetime}
        response=jsonify(authenticated=True,csrf=csrf)
        response.set_cookie(cookie,raw,max_age=lifetime,httponly=True,samesite='Strict',secure=request.is_secure,path='/api/admin')
        return response
    @bp.post('/logout')
    @protected
    def logout():
        with lock:logins.pop(hashlib.sha256(request.cookies.get(cookie,'').encode()).hexdigest(),None)
        response=jsonify(logged_out=True);response.delete_cookie(cookie,path='/api/admin');return response
    @bp.get('/study-status')
    @protected
    def study_status():
        return jsonify(privacy.study_status(notice))

    @bp.put('/study-status')
    @protected
    def update_study_status():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'enabled'} or type(body['enabled']) is not bool:
            return error('Bitte einen gültigen Freigabestatus angeben.', 400)
        try:
            return jsonify(privacy.set_study_enabled(body['enabled'], notice))
        except ValueError as failure:
            return error(str(failure), 409)

    @bp.get('/study-context')
    @protected
    def study_context_config():
        return jsonify(app.extensions['study_context'].config())

    @bp.put('/study-context')
    @protected
    def update_study_context_config():
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={'study_wave','recruitment_batch','revision'}:
            return error('Bitte Studienphase, Versandzeitpunkt und Konfigurationsrevision angeben.',400)
        try:
            return jsonify(app.extensions['study_context'].configure(**body))
        except ValueError as failure:
            return error(str(failure),409)

    @bp.get('/study-metadata')
    @protected
    def study_metadata():
        try:query,version,status,arm,prompt,wave=filters()
        except ValueError:return error('Ungültiger Filter.',400)
        from study_context import metadata_analysis
        with surveys.connect() as db:
            result=metadata_analysis(db,version=version,wave=wave or None,arm=arm or None)
        result['filter_scope']='Aktuelle Fragebogenversion, Studienphase und Gruppe; inklusive Teilnahmen ohne Antworten. Such-, Antwortstatus- und Promptfilter werden hier nicht angewandt.'
        return jsonify(result)

    @bp.get('/study-metadata-export')
    @protected
    def study_metadata_export():
        try:query,version,status,arm,prompt,wave=filters()
        except ValueError:return error('Ungültiger Filter.',400)
        import io,json,zipfile
        from study_context import metadata_analysis,scoring_csv
        from study_metrics import operation_events_csv
        with surveys.connect() as db:
            summary=metadata_analysis(db,version=version,wave=wave or None,arm=arm or None)
            identifiers={row['participation_id'] for row in summary['participants']}
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('study_metadata.json',json.dumps(summary,ensure_ascii=False,indent=2))
                archive.writestr('scoring_calls.csv',scoring_csv(db,identifiers))
                archive.writestr('operation_events.csv',operation_events_csv(db,identifiers))
                archive.writestr('README.txt','V14 Studienmetadaten inklusive Einwilligungen ohne Antworten. Filter: Version, Studienphase und Gruppe. Keine Filterung nach Antwortstatus, Suchtext oder Prompt. Pseudonymisierte Daten. Sichtbarkeit ist kein Nachweis des Lesens; ein noch nicht abgeschlossener Ablauf kann noch aktiv sein.')
        response=make_response(buffer.getvalue())
        response.headers['Content-Type']='application/zip'
        response.headers['Content-Disposition']='attachment; filename="helena_studienmetadaten.zip"'
        return response

    @bp.get('/study-analysis')
    @protected
    def study_analysis():
        return error('Die Studienauswertung ist in dieser Bereitstellung nicht enthalten.', 501)

    @bp.get('/system-prompts')
    @protected
    def get_system_prompts():
        return jsonify(system_prompts.get())

    @bp.put('/system-prompts')
    @protected
    def update_system_prompts():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'revision', 'prompts'}:
            return error('Bitte alle drei Systemprompt-Felder und ihre Revision vollständig angeben.', 400)
        try:
            updated = system_prompts.update(body['revision'], body['prompts'])
        except PromptConflict as failure:
            return error(str(failure), 409)
        except ValueError as failure:
            return error(str(failure), 400)
        return jsonify(updated)
    def filters():
        query=request.args.get('q','').strip();version=request.args.get('version',SURVEY_DEFINITION['version'])
        if len(query)>100 or version != SURVEY_DEFINITION['version']:raise ValueError()
        status=request.args.get('status','')
        if status not in ('','completed','in_progress'):raise ValueError()
        arm=request.args.get('arm','')
        if arm not in ('','A','B','C'):raise ValueError()
        prompt=request.args.get('prompt','')
        if prompt and not re.fullmatch(r'(?:unprompted|career_fixed|custom_career):[1-9][0-9]*:[a-f0-9]{64}',prompt):raise ValueError()
        wave=request.args.get('study_wave','')
        if wave=='all':wave=''
        if wave not in ('','pretest','main'):raise ValueError()
        return query,version,status,arm,prompt,wave
    @bp.get('/responses')
    @protected
    def responses():
        try:
            query,version,status,arm,prompt,wave=filters();page=int(request.args.get('page','1'))
            if not 1<=page<=100000:raise ValueError()
        except ValueError:return error('Ungültiger Filter.',400)
        base_rows=data.filtered(query,version,status,arm,study_wave=wave);rows=data.filtered(query,version,status,arm,prompt,wave);start=(page-1)*25
        return jsonify(total=len(rows),page=page,page_size=25,items=[{k:v for k,v in row.items() if k!='answers'} for row in rows[start:start+25]],
                       prompt_versions=data.prompt_versions(base_rows),selected_prompt=prompt,
                       definition=SURVEY_DEFINITION,current_release=releases.manifest)
    @bp.get('/responses/<response_id>')
    @protected
    def detail(response_id):
        row=data.detail(response_id)
        return jsonify(row) if row and row['survey_version'] == SURVEY_DEFINITION['version'] else error('Antwort nicht gefunden.',404)
    @bp.put('/responses/<response_id>')
    @protected
    def correct_response(response_id):
        existing=data.detail(response_id)
        if not existing or existing['survey_version'] != SURVEY_DEFINITION['version']:
            return error('Antwort nicht gefunden.',404)
        try:
            correction=AdminAnswerCorrection.model_validate(request.get_json(silent=True))
            data.correct(response_id,correction)
        except ValidationError:
            return error('Bitte die Antworten und den Korrekturgrund prüfen. Werte und Pflichtfelder müssen zur ursprünglichen Fragebogenversion passen.',400)
        except SurveyConflict as failure:
            return error(str(failure),409)
        except LookupError as failure:
            return error(str(failure),404)
        except ValueError as failure:
            return error(str(failure),400)
        row=data.detail(response_id)
        return jsonify(row) if row and row['survey_version'] == SURVEY_DEFINITION['version'] else error('Antwort nicht gefunden.',404)
    @bp.get('/analytics')
    @protected
    def analysis():
        try:query,version,status,arm,prompt,wave=filters()
        except ValueError:return error('Ungültiger Filter.',400)
        base_rows=data.filtered(query,version,status,arm,study_wave=wave)
        result=analytics(data.filtered(query,version,status,arm,prompt,wave),version)
        result['prompt_versions']=data.prompt_versions(base_rows)
        result['selected_prompt']=prompt
        return jsonify(result)
    @bp.get('/deletion-preview')
    @protected
    def deletion_preview():
        return jsonify(data.deletion_preview())
    @bp.get('/usage-analytics')
    @protected
    def usage_analysis():
        try:query,version,status,arm,prompt,wave=filters()
        except ValueError:return error('Ungültiger Filter.',400)
        rows=data.filtered(query,version,status,arm,prompt,wave)
        with surveys.connect() as db:
            result=telemetry_analysis(db,rows)
        return jsonify(result)
    @bp.get('/usage-export')
    @protected
    def usage_export():
        try:query,version,status,arm,prompt,wave=filters()
        except ValueError:return error('Ungültiger Filter.',400)
        rows=data.filtered(query,version,status,arm,prompt,wave)
        with surveys.connect() as db:
            content=telemetry_participant_csv(telemetry_analysis(db,rows))
        response=make_response(content)
        response.headers['Content-Type']='text/csv; charset=utf-8'
        response.headers['Content-Disposition']='attachment; filename="helena_nutzungsverhalten.csv"'
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    @bp.delete('/responses')
    @protected
    def delete_all():
        body=request.get_json(silent=True)
        if (not isinstance(body,dict) or set(body)!={'confirmation','fingerprint'}
            or body['confirmation']!='ALLE TEILNAHMEN LÖSCHEN' or not isinstance(body['fingerprint'],str)):
            return error('Bitte die vollständige Löschbestätigung eingeben.',400)
        try: result=data.delete_all(body['fingerprint'])
        except ValueError as failure:return error(str(failure),409)
        return jsonify(deleted=True,counts=result)
    @bp.delete('/responses/<response_id>')
    @protected
    def delete(response_id):
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={'confirm_id'} or not isinstance(body['confirm_id'],str):return error('Teilnahme-ID zur Bestätigung fehlt.',400)
        if not data.delete(response_id,body['confirm_id']):return error('Antwort nicht gefunden oder ID stimmt nicht überein.',409)
        return jsonify(deleted=True)
    @bp.get('/export')
    @protected
    def export():
        try:query,version,status,arm,prompt,wave=filters()
        except ValueError:return error('Ungültiger Filter.',400)
        rows=data.filtered(query,version,status,arm,prompt,wave);kind=request.args.get('format','csv')
        columns=request.args.get('columns','readable')
        if columns not in ('readable','technical'):return error('Unbekannte Spaltenbenennung.',400)
        if kind=='csv':content=data.csv_data(rows,columns=columns);filename='helena_numiqo.csv';mime='text/csv; charset=utf-8'
        elif kind=='zip':content=data.package(rows,columns=columns,study_wave=wave);filename='helena_auswertung.zip';mime='application/zip'
        else:return error('Unbekanntes Exportformat.',400)
        response=make_response(content);response.headers['Content-Type']=mime
        response.headers['Content-Disposition']=f'attachment; filename="{filename}"'
        response.headers['X-Content-Type-Options']='nosniff';return response
    @bp.get('/telemetry-export')
    @protected
    def export_telemetry():
        from study_telemetry import telemetry_csv
        try:query,version,status,arm,prompt,wave=filters()
        except ValueError:return error('Ungültiger Filter.',400)
        participants={row['participation_id'] for row in data.filtered(query,version,status,arm,prompt,wave)}
        with surveys.connect() as db:
            content=telemetry_csv(db, participation_ids=participants)
        response=make_response(content)
        response.headers['Content-Type']='text/csv; charset=utf-8'
        response.headers['Content-Disposition']='attachment; filename="helena_nutzungsereignisse.csv"'
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    app.register_blueprint(bp)

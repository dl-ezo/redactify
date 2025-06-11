#!/usr/bin/env python3
"""
Redactify Web Application
PDFから個人情報を自動検出して黒塗りするWebアプリ
"""

import os
import tempfile
import zipfile
import shutil
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from redactify import PDFRedactor
import json

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB制限
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['OUTPUT_FOLDER'] = tempfile.mkdtemp()

ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        # フォームデータの取得
        target_patterns = request.form.get('target_patterns', '').strip()
        if not target_patterns:
            return jsonify({'error': '消したい情報を入力してください'}), 400
        
        patterns = [p.strip() for p in target_patterns.split('\n') if p.strip()]
        
        # ファイルの確認
        if 'files' not in request.files:
            return jsonify({'error': 'ファイルが選択されていません'}), 400
        
        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            return jsonify({'error': 'ファイルが選択されていません'}), 400
        
        # PDFファイルのみフィルタ
        pdf_files = [f for f in files if f and allowed_file(f.filename)]
        if not pdf_files:
            return jsonify({'error': 'PDFファイルを選択してください'}), 400
        
        # セッション用の一時ディレクトリを作成
        session_dir = tempfile.mkdtemp()
        upload_dir = os.path.join(session_dir, 'uploads')
        output_dir = os.path.join(session_dir, 'outputs')
        os.makedirs(upload_dir)
        os.makedirs(output_dir)
        
        # ファイルを保存
        uploaded_files = []
        for file in pdf_files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(upload_dir, filename)
                file.save(filepath)
                uploaded_files.append(filepath)
        
        # AI設定を環境変数/.env優先で取得
        def get_bool_setting(env_var, default):
            env_value = os.getenv(env_var)
            if env_value is not None:
                return env_value.lower() in ('true', '1', 'yes', 'on')
            return default
        
        # config.jsonからデフォルト設定を読み込み
        config_ai_settings = {}
        if os.path.exists('./config.json'):
            try:
                with open('./config.json', 'r', encoding='utf-8') as f:
                    existing_config = json.load(f)
                    config_ai_settings = existing_config.get('ai_api', {})
            except Exception as e:
                print(f"DEBUG: config.json読み込みエラー: {e}")
        
        # 環境変数/.env優先、config.jsonでフォールバック
        provider = os.getenv('AI_PROVIDER') or config_ai_settings.get('provider', 'anthropic')
        model = os.getenv('AI_MODEL') or config_ai_settings.get('model', 'claude-3-haiku-20240307')
        enabled = get_bool_setting('AI_ENABLED', config_ai_settings.get('enabled', False))
        
        # APIキーの取得（プロバイダーに応じて適切な環境変数を使用）
        if provider == 'openai':
            api_key = os.getenv('OPENAI_API_KEY') or config_ai_settings.get('api_key')
        else:  # anthropic
            api_key = os.getenv('ANTHROPIC_API_KEY') or config_ai_settings.get('api_key')
        
        ai_config = {
            'provider': provider,
            'model': model,
            'enabled': enabled,
            'api_key': api_key
        }
        
        # 設定を作成
        config = {
            'target_patterns': patterns,
            'folders': {
                'input_dir': upload_dir,
                'output_dir': output_dir
            },
            'ai_api': ai_config
        }
        
        # 設定ファイルを作成
        config_path = os.path.join(session_dir, 'config.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        # 黒塗り処理
        redactor = PDFRedactor(config_path)
        processed_files = []
        total_redacted = 0
        
        print(f"DEBUG: Processing {len(uploaded_files)} files with patterns: {patterns}")
        
        for filepath in uploaded_files:
            try:
                print(f"DEBUG: Processing {filepath}")
                output_path, count = redactor.redact_pdf(filepath)
                print(f"DEBUG: Found {count} matches in {filepath}")
                processed_files.append({
                    'original': os.path.basename(filepath),
                    'output': output_path,
                    'count': count
                })
                total_redacted += count
            except Exception as e:
                print(f"DEBUG: Error processing {filepath}: {e}")
                processed_files.append({
                    'original': os.path.basename(filepath),
                    'error': str(e)
                })
        
        # ZIPファイルを作成
        zip_path = os.path.join(session_dir, 'redacted_files.zip')
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file_info in processed_files:
                if 'output' in file_info:
                    zipf.write(file_info['output'], os.path.basename(file_info['output']))
        
        return jsonify({
            'success': True,
            'session_dir': session_dir,
            'zip_path': zip_path,
            'processed_files': processed_files,
            'total_redacted': total_redacted
        })
        
    except Exception as e:
        return jsonify({'error': f'処理中にエラーが発生しました: {str(e)}'}), 500

@app.route('/download')
def download_zip():
    try:
        session_dir = request.args.get('session_dir')
        if not session_dir:
            return jsonify({'error': 'セッションIDが指定されていません'}), 400
        
        # セキュリティチェック
        if not session_dir.startswith('/tmp/'):
            return jsonify({'error': '不正なセッションです'}), 400
        
        zip_path = os.path.join(session_dir, 'redacted_files.zip')
        if not os.path.exists(zip_path):
            return jsonify({'error': 'ファイルが見つかりません'}), 404
        
        return send_file(
            zip_path,
            as_attachment=True,
            download_name='redacted_files.zip',
            mimetype='application/zip'
        )
        
    except Exception as e:
        return jsonify({'error': f'ダウンロードエラー: {str(e)}'}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    try:
        data = request.get_json()
        session_dir = data.get('session_dir') if data else None
        
        if not session_dir:
            return jsonify({'error': 'セッションIDが指定されていません'}), 400
        
        # セキュリティチェック
        if not session_dir.startswith('/tmp/'):
            return jsonify({'error': '不正なセッションです'}), 400
        
        if os.path.exists(session_dir):
            shutil.rmtree(session_dir)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': f'クリーンアップエラー: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
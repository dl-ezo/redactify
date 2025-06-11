#!/usr/bin/env python3
"""
Redactify Web Application
PDFから個人情報を自動検出して黒塗りするWebアプリ
"""

import os
import zipfile
import io
import subprocess
from flask import Flask, render_template, request, jsonify, send_file, Response
from werkzeug.utils import secure_filename
from redactify import PDFRedactor
import json
import uuid

def get_version():
    """GitタグからバージョンIを動的取得"""
    try:
        # 最新のGitタグを取得
        result = subprocess.run(
            ['git', 'describe', '--tags', '--abbrev=0'],
            capture_output=True, text=True, cwd=os.getcwd(), timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            # フォールバック: コミットハッシュ
            result = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                capture_output=True, text=True, timeout=5
            )
            return f"dev-{result.stdout.strip()}" if result.returncode == 0 else "dev"
    except Exception as e:
        print(f"Version detection error: {e}")
        return "dev"

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB制限

# アプリ起動時にバージョンを取得
app.config['VERSION'] = get_version()
print(f"Redactify starting with version: {app.config['VERSION']}")

ALLOWED_EXTENSIONS = {'pdf'}

# メモリ内でZIPファイルを一時保存
memory_store = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html', version=app.config['VERSION'])

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
        
        # メモリ内でPDF処理
        from redactify import AIAddressMatcher
        ai_matcher = AIAddressMatcher(ai_config) if ai_config.get('enabled') else None
        
        processed_files = []
        total_redacted = 0
        zip_buffer = io.BytesIO()
        
        print(f"DEBUG: Processing {len(pdf_files)} files with patterns: {patterns}")
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in pdf_files:
                try:
                    filename = secure_filename(file.filename)
                    print(f"DEBUG: Processing {filename}")
                    
                    # メモリ内でPDF処理
                    file_data = file.read()
                    output_data, count = process_pdf_in_memory(file_data, patterns, ai_matcher)
                    
                    print(f"DEBUG: Found {count} matches in {filename}")
                    
                    # ZIPに追加
                    output_filename = filename.replace('.pdf', '_redacted.pdf')
                    zipf.writestr(output_filename, output_data)
                    
                    processed_files.append({
                        'original': filename,
                        'output': output_filename,
                        'count': count
                    })
                    total_redacted += count
                    
                except Exception as e:
                    print(f"DEBUG: Error processing {filename}: {e}")
                    processed_files.append({
                        'original': filename,
                        'error': str(e)
                    })
        
        # セッションIDを生成してメモリに保存
        session_id = str(uuid.uuid4())
        zip_buffer.seek(0)
        memory_store[session_id] = {
            'data': zip_buffer.getvalue(),
            'filename': 'redacted_files.zip',
            'processed_files': processed_files,
            'total_redacted': total_redacted
        }
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'processed_files': processed_files,
            'total_redacted': total_redacted
        })
        
    except Exception as e:
        return jsonify({'error': f'処理中にエラーが発生しました: {str(e)}'}), 500

def process_pdf_in_memory(pdf_data, patterns, ai_matcher):
    """メモリ内でPDFを処理"""
    import fitz
    
    # メモリからPDFを開く
    doc = fitz.open(stream=pdf_data, filetype="pdf")
    redacted_count = 0
    
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            
            # 住所を検出
            addresses = []
            
            # AIファジーマッチング
            if ai_matcher and ai_matcher.ai_enabled:
                ai_addresses = ai_matcher.find_similar_patterns(text, patterns)
                addresses.extend(ai_addresses)
            
            # 基本パターンマッチング
            import re
            for pattern in patterns:
                escaped_pattern = re.escape(pattern)
                matches = re.finditer(escaped_pattern, text)
                for match in matches:
                    new_addr = {
                        'text': match.group(),
                        'start': match.start(),
                        'end': match.end()
                    }
                    # 重複を避ける
                    if not any(addr['text'] == new_addr['text'] for addr in addresses):
                        addresses.append(new_addr)
            
            # 黒塗り実行
            for addr in addresses:
                text_instances = page.search_for(addr['text'])
                for inst in text_instances:
                    adjusted_rect = fitz.Rect(
                        inst.x0 - 1, inst.y0 - 1,
                        inst.x1 + 1, inst.y1 + 1
                    )
                    redact_annot = page.add_redact_annot(adjusted_rect)
                    redact_annot.set_colors({"fill": (0, 0, 0)})
                    redacted_count += 1
            
            # 黒塗りを適用
            page.apply_redactions()
        
        # メモリ内でPDFを保存
        output_data = doc.tobytes()
        return output_data, redacted_count
        
    finally:
        doc.close()

@app.route('/download')
def download_zip():
    try:
        session_id = request.args.get('session_id')
        if not session_id:
            return jsonify({'error': 'セッションIDが指定されていません'}), 400
        
        # メモリから取得
        if session_id not in memory_store:
            return jsonify({'error': 'ファイルが見つかりません'}), 404
        
        stored_data = memory_store[session_id]
        
        return Response(
            stored_data['data'],
            mimetype='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename={stored_data["filename"]}'
            }
        )
        
    except Exception as e:
        return jsonify({'error': f'ダウンロードエラー: {str(e)}'}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    try:
        data = request.get_json()
        session_id = data.get('session_id') if data else None
        
        if not session_id:
            return jsonify({'error': 'セッションIDが指定されていません'}), 400
        
        # メモリから削除
        if session_id in memory_store:
            del memory_store[session_id]
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': f'クリーンアップエラー: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
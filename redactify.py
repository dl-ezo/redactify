#!/usr/bin/env python3
"""
PDFから個人情報（住所）を自動検出して黒塗りするツール
"""

import re
import sys
import click
import os
import json
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
from io import BytesIO
import anthropic
import openai
from dotenv import load_dotenv
import logging


# 環境変数を読み込み
load_dotenv()

class AIAddressMatcher:
    def __init__(self, config):
        self.config = config
        self.ai_enabled = config.get('enabled', False)
        self.provider = config.get('provider', 'anthropic')
        self.api_key = config.get('api_key') or os.getenv('ANTHROPIC_API_KEY') or os.getenv('OPENAI_API_KEY')
        self.model = config.get('model', 'claude-3-haiku-20240307')
        
        if self.ai_enabled and not self.api_key:
            logging.warning("AI機能が有効ですがAPIキーが設定されていません")
            self.ai_enabled = False
    
    def find_similar_patterns(self, text, target_patterns):
        """AIを使って類似する住所表現を検出"""
        if not self.ai_enabled or not target_patterns:
            return []
        
        try:
            prompt = f"""以下のテキストから、指定されたパターンと類似する表現を全て抽出してください。
            
対象パターン: {', '.join(target_patterns)}
            
テキスト:
{text}
            
以下の条件で抽出してください：
- 指定されたパターンの一部でも一致する表現
- 漢字、ひらがな、カタカナ、数字、記号の違いは無視
- 表記揺れ（例：１と1、－と-、丁目と丁目）も含める
- 完全一致でなくても、パターンの一部が含まれていれば抽出
            
結果は以下のJSON形式で返してください：
[["抽出されたテキスト1", 開始位置, 終了位置], ["抽出されたテキスト2", 開始位置, 終了位置], ...]
            
該当なしの場合は空配列[]を返してください。"""
            
            if self.provider == 'anthropic':
                client = anthropic.Anthropic(api_key=self.api_key)
                response = client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}]
                )
                result_text = response.content[0].text
            else:  # OpenAI
                client = openai.OpenAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model=self.model if 'gpt' in self.model else 'gpt-3.5-turbo',
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1000
                )
                result_text = response.choices[0].message.content
            
            # JSONをパース（JSON部分のみ抽出）
            try:
                # JSON配列の開始と終了を見つける
                start_idx = result_text.find('[')
                end_idx = result_text.rfind(']') + 1
                
                if start_idx != -1 and end_idx > start_idx:
                    json_str = result_text[start_idx:end_idx]
                    matches = json.loads(json_str)
                    addresses = []
                    for match in matches:
                        if len(match) >= 3:
                            addresses.append({
                                'text': match[0],
                                'start': match[1],
                                'end': match[2]
                            })
                    return addresses
                else:
                    logging.error(f"AI応答にJSON配列が見つかりません: {result_text}")
                    return []
            except json.JSONDecodeError:
                logging.error(f"AI応答のJSONパースに失敗: {result_text}")
                return []
                
        except Exception as e:
            logging.error(f"AIパターン検出エラー: {e}")
            return []

class PDFRedactor:
    def __init__(self, config_path=None):
        self.address_patterns = []
        self.input_dir = None
        self.output_dir = None
        self.target_patterns = []
        self.ai_matcher = None
        
        # 設定ファイルがあれば読み込み
        if config_path and os.path.exists(config_path):
            self.load_config(config_path)
        
        # パターンが設定されていない場合はエラー
        if not self.target_patterns and not self.address_patterns:
            raise ValueError("エラー: target_patternsまたはlegacy_patternsを設定してください")
    
    def load_config(self, config_path):
        """設定ファイルから住所パターンを読み込み"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # フォルダ設定
            if 'folders' in config:
                self.input_dir = config['folders'].get('input_dir')
                self.output_dir = config['folders'].get('output_dir')
            
            # AI設定
            if 'ai_api' in config:
                self.ai_matcher = AIAddressMatcher(config['ai_api'])
            
            # ターゲットパターン
            if 'target_patterns' in config:
                self.target_patterns = config['target_patterns']
            
            # レガシーパターンの読み込み（後方互換性）
            patterns = []
            legacy_config = config.get('legacy_patterns', config)  # legacy_patternsがない場合はルートを使用
            
            # 郵便番号パターン
            if 'postal_codes' in legacy_config:
                for code in legacy_config['postal_codes']:
                    patterns.append(re.escape(code))
            
            # 都道府県パターン
            if 'prefectures' in legacy_config:
                for pref in legacy_config['prefectures']:
                    patterns.append(re.escape(pref))
            
            # 市区町村パターン
            if 'cities' in legacy_config:
                for city in legacy_config['cities']:
                    patterns.append(re.escape(city))
            
            # 住所パターン
            if 'addresses' in legacy_config:
                for addr in legacy_config['addresses']:
                    patterns.append(re.escape(addr))
            
            # カスタムパターン（正規表現）
            if 'custom_patterns' in legacy_config:
                patterns.extend(legacy_config['custom_patterns'])
            
            # 設定があればパターンを設定
            if patterns:
                self.address_patterns = patterns
                
        except Exception as e:
            click.echo(f"設定ファイル読み込みエラー: {e}", err=True)
        
    def detect_addresses(self, text):
        """テキストからパターンを検出"""
        addresses = []
        
        # AIファジーマッチングを先に実行
        if self.ai_matcher and self.ai_matcher.ai_enabled and self.target_patterns:
            ai_addresses = self.ai_matcher.find_similar_patterns(text, self.target_patterns)
            addresses.extend(ai_addresses)
        
        # レガシーパターンマッチング
        for pattern in self.address_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                new_addr = {
                    'text': match.group(),
                    'start': match.start(),
                    'end': match.end()
                }
                # 重複を避けるため、既に同じテキストがないかチェック
                if not any(addr['text'] == new_addr['text'] for addr in addresses):
                    addresses.append(new_addr)
        
        return addresses
    
    def redact_to_image(self, input_path, output_path=None, dpi=300):
        """PDFを画像に変換してから住所を黒塗り"""
        if not output_path:
            name, ext = os.path.splitext(os.path.basename(input_path))
            if self.output_dir:
                # 出力フォルダが設定されている場合
                os.makedirs(self.output_dir, exist_ok=True)
                output_path = os.path.join(self.output_dir, f"{name}_redacted.png")
            else:
                output_path = f"{name}_redacted.png"
        
        doc = fitz.open(input_path)
        redacted_count = 0
        
        # 最初のページのみ処理（複数ページ対応は後で拡張可能）
        page = doc[0]
        
        # PDFページを画像に変換
        mat = fitz.Matrix(dpi/72, dpi/72)  # DPIを設定
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        
        # PIL Imageに変換
        img = Image.open(BytesIO(img_data))
        draw = ImageDraw.Draw(img)
        
        # テキストを抽出
        text = page.get_text()
        
        # 住所を検出
        addresses = self.detect_addresses(text)
        
        for addr in addresses:
            # テキスト検索して位置を特定
            text_instances = page.search_for(addr['text'])
            for inst in text_instances:
                # 座標をDPIに合わせてスケール
                scale = dpi / 72
                x0 = int(inst.x0 * scale)
                y0 = int(inst.y0 * scale)
                x1 = int(inst.x1 * scale)
                y1 = int(inst.y1 * scale)
                
                # 黒い矩形で塗りつぶし
                draw.rectangle([x0-2, y0-2, x1+2, y1+2], fill='black')
                redacted_count += 1
        
        # 画像を保存
        img.save(output_path)
        doc.close()
        
        return output_path, redacted_count
    
    def redact_pdf(self, input_path, output_path=None):
        """PDFから住所を検出して黒塗り（PDF出力）"""
        if not output_path:
            name, ext = os.path.splitext(os.path.basename(input_path))
            if self.output_dir:
                # 出力フォルダが設定されている場合
                os.makedirs(self.output_dir, exist_ok=True)
                output_path = os.path.join(self.output_dir, f"{name}_redacted{ext}")
            else:
                output_path = f"{name}_redacted{ext}"
        
        doc = fitz.open(input_path)
        redacted_count = 0
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            
            # 住所を検出
            addresses = self.detect_addresses(text)
            
            for addr in addresses:
                # テキスト検索して正確な位置を特定
                text_instances = page.search_for(addr['text'])
                for inst in text_instances:
                    # テキストサイズに合わせて矩形を調整
                    adjusted_rect = fitz.Rect(
                        inst.x0 - 1,  # 左端を少し広げる
                        inst.y0 - 1,  # 上端を少し広げる
                        inst.x1 + 1,  # 右端を少し広げる
                        inst.y1 + 1   # 下端を少し広げる
                    )
                    redact_annot = page.add_redact_annot(adjusted_rect)
                    # 黒塗りの色を設定
                    redact_annot.set_colors({"fill": (0, 0, 0)})  # 黒色
                    redacted_count += 1
            
            # 黒塗りを適用
            page.apply_redactions()
        
        doc.save(output_path)
        doc.close()
        
        return output_path, redacted_count


def resolve_input_path(redactor, input_file):
    """入力ファイルパスを解決"""
    if os.path.isabs(input_file) or redactor.input_dir is None:
        return input_file
    
    # 設定で入力フォルダが指定されている場合
    resolved_path = os.path.join(redactor.input_dir, os.path.basename(input_file))
    if os.path.exists(resolved_path):
        return resolved_path
    
    # 元のパスが存在する場合はそちらを使用
    if os.path.exists(input_file):
        return input_file
    
    return resolved_path

def get_pdf_files(redactor):
    """入力フォルダからすべてのPDFファイルを取得"""
    input_dir = redactor.input_dir or './input'
    
    if not os.path.exists(input_dir):
        return []
    
    pdf_files = []
    for filename in os.listdir(input_dir):
        if filename.lower().endswith('.pdf'):
            pdf_files.append(os.path.join(input_dir, filename))
    
    return sorted(pdf_files)

@click.command()
@click.argument('input_file', type=click.Path(), required=False)
@click.option('--output', '-o', help='出力ファイル名（省略時は設定フォルダまたは元ファイル名_redacted）')
@click.option('--preview', '-p', is_flag=True, help='検出された住所をプレビュー表示')
@click.option('--config', '-c', help='設定ファイルのパス（JSON形式）')
@click.option('--image', '-i', is_flag=True, help='画像として出力（PNG形式）')
@click.option('--all', '-a', is_flag=True, help='入力フォルダ内のすべてのPDFを処理')
def main(input_file, output, preview, config, image, all):
    """PDFから個人情報（住所）を自動検出して黒塗りします"""
    
    # --configが指定されていない場合、カレントディレクトリのconfig.jsonを探す
    if not config and os.path.exists('./config.json'):
        config = './config.json'
    
    redactor = PDFRedactor(config)
    
    # すべてのPDFを処理するか、特定のファイルのみか判定
    if all or not input_file:
        pdf_files = get_pdf_files(redactor)
        if not pdf_files:
            input_dir = redactor.input_dir or './input'
            click.echo(f"エラー: {input_dir} にPDFファイルが見つかりません", err=True)
            sys.exit(1)
        
        click.echo(f"{len(pdf_files)} 個のPDFファイルを処理します:")
        for pdf_file in pdf_files:
            click.echo(f"  - {os.path.basename(pdf_file)}")
        
        if preview:
            # プレビューモード：すべてのファイルの住所を表示
            total_addresses = 0
            for pdf_file in pdf_files:
                click.echo(f"\n--- {os.path.basename(pdf_file)} ---")
                found_addresses = []
                
                doc = fitz.open(pdf_file)
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    text = page.get_text()
                    addresses = redactor.detect_addresses(text)
                    
                    for addr in addresses:
                        found_addresses.append(f"ページ{page_num + 1}: {addr['text']}")
                
                doc.close()
                
                if found_addresses:
                    for addr in found_addresses:
                        click.echo(f"  - {addr}")
                    click.echo(f"このファイルで {len(found_addresses)} 件の住所が検出されました")
                    total_addresses += len(found_addresses)
                else:
                    click.echo("  住所は検出されませんでした")
            
            click.echo(f"\n合計 {total_addresses} 件の住所が検出されました")
        else:
            # 黒塗り実行：すべてのファイル
            total_redacted = 0
            success_count = 0
            
            for pdf_file in pdf_files:
                try:
                    if image:
                        output_path, count = redactor.redact_to_image(pdf_file)
                    else:
                        output_path, count = redactor.redact_pdf(pdf_file)
                    
                    click.echo(f"✓ {os.path.basename(pdf_file)}: {count} 件の住所を黒塗り → {os.path.basename(output_path)}")
                    total_redacted += count
                    success_count += 1
                except Exception as e:
                    click.echo(f"✗ {os.path.basename(pdf_file)}: エラー - {e}", err=True)
            
            click.echo(f"\n完了: {success_count}/{len(pdf_files)} ファイル処理済み、合計 {total_redacted} 件の住所を黒塗りしました")
    
    else:
        # 単一ファイル処理（従来の動作）
        if not input_file.lower().endswith('.pdf'):
            click.echo("エラー: PDFファイルを指定してください", err=True)
            sys.exit(1)
        
        # 入力ファイルパスを解決
        resolved_input = resolve_input_path(redactor, input_file)
        if not os.path.exists(resolved_input):
            click.echo(f"エラー: ファイルが見つかりません: {resolved_input}", err=True)
            sys.exit(1)
        
        if preview:
            # プレビューモード：検出された住所を表示
            doc = fitz.open(resolved_input)
            found_addresses = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()
                addresses = redactor.detect_addresses(text)
                
                for addr in addresses:
                    found_addresses.append(f"ページ{page_num + 1}: {addr['text']}")
            
            doc.close()
            
            if found_addresses:
                click.echo("検出された住所:")
                for addr in found_addresses:
                    click.echo(f"  - {addr}")
                click.echo(f"\n合計 {len(found_addresses)} 件の住所が検出されました")
            else:
                click.echo("住所は検出されませんでした")
        else:
            # 黒塗り実行
            try:
                if image:
                    # 画像として出力
                    output_path, count = redactor.redact_to_image(resolved_input, output)
                else:
                    # PDFとして出力
                    output_path, count = redactor.redact_pdf(resolved_input, output)
                
                click.echo(f"✓ 完了: {count} 件の住所を黒塗りしました")
                click.echo(f"✓ 出力: {output_path}")
            except Exception as e:
                click.echo(f"エラー: {e}", err=True)
                sys.exit(1)


if __name__ == '__main__':
    main()
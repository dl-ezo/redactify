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


class PDFRedactor:
    def __init__(self, config_path=None):
        # デフォルトパターン
        self.default_patterns = [
            r'〒\d{3}-\d{4}',
            r'神奈川県',
            r'横浜市[^。、\s\n]*',
            r'\d+[-−]\d+[-−]\d+[-−]\d+',
        ]
        
        self.address_patterns = self.default_patterns.copy()
        
        # 設定ファイルがあれば読み込み
        if config_path and os.path.exists(config_path):
            self.load_config(config_path)
    
    def load_config(self, config_path):
        """設定ファイルから住所パターンを読み込み"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            patterns = []
            
            # 郵便番号パターン
            if 'postal_codes' in config:
                for code in config['postal_codes']:
                    patterns.append(re.escape(code))
            
            # 都道府県パターン
            if 'prefectures' in config:
                for pref in config['prefectures']:
                    patterns.append(re.escape(pref))
            
            # 市区町村パターン
            if 'cities' in config:
                for city in config['cities']:
                    patterns.append(re.escape(city))
            
            # 住所パターン
            if 'addresses' in config:
                for addr in config['addresses']:
                    patterns.append(re.escape(addr))
            
            # カスタムパターン（正規表現）
            if 'custom_patterns' in config:
                patterns.extend(config['custom_patterns'])
            
            # 設定があればデフォルトパターンと組み合わせ
            if patterns:
                self.address_patterns = patterns
                
        except Exception as e:
            click.echo(f"設定ファイル読み込みエラー: {e}", err=True)
        
    def detect_addresses(self, text):
        """テキストから住所を検出"""
        addresses = []
        for pattern in self.address_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                addresses.append({
                    'text': match.group(),
                    'start': match.start(),
                    'end': match.end()
                })
        return addresses
    
    def redact_to_image(self, input_path, output_path=None, dpi=300):
        """PDFを画像に変換してから住所を黒塗り"""
        if not output_path:
            name, ext = os.path.splitext(input_path)
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
            name, ext = os.path.splitext(input_path)
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


@click.command()
@click.argument('input_file', type=click.Path(exists=True))
@click.option('--output', '-o', help='出力ファイル名（省略時は元ファイル名_redacted.pdf/.png）')
@click.option('--preview', '-p', is_flag=True, help='検出された住所をプレビュー表示')
@click.option('--config', '-c', help='設定ファイルのパス（JSON形式）')
@click.option('--image', '-i', is_flag=True, help='画像として出力（PNG形式）')
def main(input_file, output, preview, config, image):
    """PDFから個人情報（住所）を自動検出して黒塗りします"""
    
    if not input_file.lower().endswith('.pdf'):
        click.echo("エラー: PDFファイルを指定してください", err=True)
        sys.exit(1)
    
    redactor = PDFRedactor(config)
    
    if preview:
        # プレビューモード：検出された住所を表示
        doc = fitz.open(input_file)
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
                output_path, count = redactor.redact_to_image(input_file, output)
            else:
                # PDFとして出力
                output_path, count = redactor.redact_pdf(input_file, output)
            
            click.echo(f"✓ 完了: {count} 件の住所を黒塗りしました")
            click.echo(f"✓ 出力: {output_path}")
        except Exception as e:
            click.echo(f"エラー: {e}", err=True)
            sys.exit(1)


if __name__ == '__main__':
    main()
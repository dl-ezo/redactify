document.addEventListener('DOMContentLoaded', function() {
    const uploadForm = document.getElementById('uploadForm');
    const processing = document.getElementById('processing');
    const results = document.getElementById('results');
    const error = document.getElementById('error');
    const downloadBtn = document.getElementById('downloadBtn');
    const resetBtn = document.getElementById('resetBtn');
    const retryBtn = document.getElementById('retryBtn');
    
    let currentSessionDir = null;
    
    uploadForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // UI状態をリセット
        hideAllSections();
        processing.style.display = 'block';
        processing.classList.add('fade-in');
        
        const formData = new FormData(uploadForm);
        
        fetch('/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            processing.style.display = 'none';
            
            if (data.success) {
                showResults(data);
            } else {
                showError(data.error || '不明なエラーが発生しました');
            }
        })
        .catch(err => {
            processing.style.display = 'none';
            showError('サーバーとの通信に失敗しました: ' + err.message);
        });
    });
    
    downloadBtn.addEventListener('click', function() {
        if (currentSessionDir) {
            const downloadUrl = `/download?session_dir=${encodeURIComponent(currentSessionDir)}`;
            window.location.href = downloadUrl;
        }
    });
    
    resetBtn.addEventListener('click', function() {
        resetForm();
    });
    
    retryBtn.addEventListener('click', function() {
        hideAllSections();
    });
    
    function showResults(data) {
        currentSessionDir = data.session_dir;
        
        const resultSummary = document.getElementById('resultSummary');
        resultSummary.textContent = `${data.processed_files.length}個のファイルを処理し、合計${data.total_redacted}件の情報を黒塗りしました。`;
        
        const fileList = document.getElementById('fileList');
        fileList.innerHTML = '';
        
        data.processed_files.forEach(file => {
            const fileItem = document.createElement('div');
            fileItem.className = 'file-item';
            
            if (file.error) {
                fileItem.classList.add('error');
                fileItem.innerHTML = `
                    <i class="fas fa-exclamation-triangle text-danger"></i> 
                    <strong>${file.original}</strong>: ${file.error}
                `;
            } else {
                fileItem.innerHTML = `
                    <i class="fas fa-check text-success"></i> 
                    <strong>${file.original}</strong>: ${file.count}件の情報を黒塗り
                `;
            }
            
            fileList.appendChild(fileItem);
        });
        
        results.style.display = 'block';
        results.classList.add('fade-in');
    }
    
    function showError(message) {
        const errorMessage = document.getElementById('errorMessage');
        errorMessage.textContent = message;
        error.style.display = 'block';
        error.classList.add('fade-in');
    }
    
    function hideAllSections() {
        processing.style.display = 'none';
        results.style.display = 'none';
        error.style.display = 'none';
        
        // アニメーションクラスを削除
        processing.classList.remove('fade-in');
        results.classList.remove('fade-in');
        error.classList.remove('fade-in');
    }
    
    function resetForm() {
        // セッションをクリーンアップ
        if (currentSessionDir) {
            fetch('/cleanup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({session_dir: currentSessionDir})
            }).catch(err => console.error('クリーンアップエラー:', err));
            currentSessionDir = null;
        }
        
        // フォームとUIをリセット
        uploadForm.reset();
        hideAllSections();
    }
    
    // ファイル選択時のプレビュー
    const filesInput = document.getElementById('files');
    filesInput.addEventListener('change', function() {
        const fileCount = this.files.length;
        if (fileCount > 0) {
            const fileText = this.parentElement.querySelector('.form-text');
            fileText.innerHTML = `
                <i class="fas fa-check-circle text-success"></i> 
                ${fileCount}個のPDFファイルが選択されました
            `;
        }
    });
    
    // ページを離れる前にクリーンアップ
    window.addEventListener('beforeunload', function() {
        if (currentSessionDir) {
            const data = JSON.stringify({session_dir: currentSessionDir});
            navigator.sendBeacon('/cleanup', data);
        }
    });
});
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
import re
import yt_dlp
import os

app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

SAVENOW_API_TOKEN = os.environ.get('SAVENOW_API_TOKEN', '5145e3dae06a4e0686d967ad556f10acad90adc3')
SAVENOW_API_KEY = os.environ.get('SAVENOW_API_KEY', '5145e3dae06a4e0686d967ad556f10acad90adc3')
SAVENOW_BASE_URL = 'https://pauline27.savenow.to'

def get_auth_headers():
    return {
        'Authorization': f'Bearer {SAVENOW_API_TOKEN}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Referer': f'{SAVENOW_BASE_URL}/'
    }

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/search', methods=['GET'])
def search_media():
    query = request.args.get('q')
    print(f"[SEARCH_ENDPOINT] Received query: {query}")
    if not query:
        print("[SEARCH_ENDPOINT] Error: Query required")
        return jsonify({'success': False, 'error': 'Query required'}), 400

    yt_regex = r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})'
    match = re.search(yt_regex, query)

    if match:
        video_id = match.group(1)
        print(f"[SEARCH_ENDPOINT] Direct YouTube URL detected, ID: {video_id}")
        return jsonify({
            'success': True,
            'isDirectUrl': True,
            'results': [{
                'id': video_id,
                'url': f'https://www.youtube.com/watch?v={video_id}',
                'title': f'YouTube Video ({video_id})',
                'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
                'duration': 'N/A',
                'author': 'YouTube',
                'views': 0
            }]
        })

    ydl_opts = {'extract_flat': True, 'max_downloads': 16, 'quiet': True}
    try:
        print("[SEARCH_ENDPOINT] Executing yt_dlp search...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch16:{query}", download=False)
            videos = []
            for entry in search_results.get('entries', []):
                videos.append({
                    'id': entry.get('id'),
                    'url': entry.get('url'),
                    'title': entry.get('title'),
                    'thumbnail': entry.get('thumbnail'),
                    'duration': str(entry.get('duration', 'N/A')),
                    'author': entry.get('uploader', 'Unknown Artist'),
                    'views': entry.get('view_count', 0)
                })
            print(f"[SEARCH_ENDPOINT] Found {len(videos)} results via yt_dlp")
            return jsonify({'success': True, 'isDirectUrl': False, 'results': videos})
    except Exception as e:
        print(f"[SEARCH_ENDPOINT] Search failed with exception: {str(e)}")
        return jsonify({'success': False, 'error': 'Search failed'}), 500

@app.route('/api/download', methods=['GET'])
def download_media():
    target_url = f"{SAVENOW_BASE_URL}/ajax/download.php"
    params = {
        'url': request.args.get('url'),
        'format': request.args.get('format'),
        'apikey': SAVENOW_API_KEY,
        'add_info': '1'
    }
    print(f"[DOWNLOAD_ENDPOINT] Requesting upstream download endpoint: {target_url}")
    try:
        response = requests.get(target_url, params=params, headers=get_auth_headers(), timeout=15)
        print(f"[DOWNLOAD_ENDPOINT] Upstream status code: {response.status_code}")
        print(f"[DOWNLOAD_ENDPOINT] Upstream raw body: {response.text}")
        return jsonify(response.json())
    except Exception as e:
        print(f"[DOWNLOAD_ENDPOINT] Download initiation failed with exception: {str(e)}")
        return jsonify({'success': False, 'error': 'Download initiation failed'}), 500

@app.route('/api/progress', methods=['GET'])
def check_progress():
    job_id = request.args.get('id')
    target_url = f"{SAVENOW_BASE_URL}/api/progress"
    params = {'id': job_id, 'apikey': SAVENOW_API_KEY}
    print(f"[PROGRESS_ENDPOINT] Checking progress for ID: {job_id} at {target_url}")
    try:
        response = requests.get(target_url, params=params, headers=get_auth_headers(), timeout=15)
        print(f"[PROGRESS_ENDPOINT] Upstream status code: {response.status_code}")
        print(f"[PROGRESS_ENDPOINT] Upstream raw body: {response.text}")

        data = response.json()
        raw_download_url = data.get('download_url')
        print(f"[PROGRESS_ENDPOINT] Parsed download_url from upstream: {raw_download_url}")

        if raw_download_url and (data.get('progress') == 1000 or data.get('text') == 'Finished'):
            print("[PROGRESS_ENDPOINT] Job finished, walking redirect chain to bypass ad wrappers...")
            try:
                session = requests.Session()
                current_url = raw_download_url
                for _ in range(5):
                    res = session.get(current_url, headers=get_auth_headers(), allow_redirects=False, timeout=15)
                    print(f"[PROGRESS_ENDPOINT] Hop URL: {current_url} -> Status: {res.status_code}")
                    if res.status_code in [301, 302, 303, 307, 308]:
                        next_url = res.headers.get('Location')
                        print(f"[PROGRESS_ENDPOINT] Redirect location: {next_url}")
                        if next_url:
                            if '/ajax/ad/' in next_url or 'ey43.com' in next_url:
                                print("[PROGRESS_ENDPOINT] Detected ad hop, ignoring ad redirect...")
                                break
                            current_url = next_url
                    else:
                        current_url = res.url
                        break

                if '/ajax/ad/' not in current_url and 'ey43.com' not in current_url:
                    data['download_url'] = current_url
                    print(f"[PROGRESS_ENDPOINT] Successfully resolved clean target: {data['download_url']}")
            except Exception as res_err:
                print(f"[PROGRESS_ENDPOINT] Error resolving redirect chain: {str(res_err)}")
                pass

        return jsonify(data)
    except Exception as e:
        print(f"[PROGRESS_ENDPOINT] Progress check failed with exception: {str(e)}")
        return jsonify({'success': False, 'error': 'Progress check failed'}), 500

@app.route('/api/stream', methods=['GET'])
def stream_media():
    url = request.args.get('url')
    title = request.args.get('title', 'media_file')
    fmt = request.args.get('format', 'mp3')
    print(f"[STREAM_ENDPOINT] Received stream request for URL: {url}, Title: {title}, Format: {fmt}")

    if not url:
        print("[STREAM_ENDPOINT] Error: URL required")
        return 'URL required', 400

    if url.startswith('http://'):
        url = url.replace('http://', 'https://')

    ext = 'mp3' if fmt == 'mp3' else 'mp4'
    clean_title = re.sub(r'[^a-zA-Z0-9 _-]', '', title).strip() or 'media_file'

    try:
        req_headers = {
            'Authorization': f'Bearer {SAVENOW_API_TOKEN}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Referer': f'{SAVENOW_BASE_URL}/',
            'Accept': '*/*'
        }

        print(f"[STREAM_ENDPOINT] Opening requests session to fetch stream target...")
        session = requests.Session()
        r = session.get(url, headers=req_headers, stream=True, allow_redirects=True, timeout=60)

        content_type = r.headers.get('content-type', '').lower()
        content_length_str = r.headers.get('content-length', '0')
        try:
            content_length = int(content_length_str)
        except ValueError:
            content_length = 0

        print(f"[STREAM_ENDPOINT] Stream target response status code: {r.status_code}")
        print(f"[STREAM_ENDPOINT] Stream target content-type: {content_type}")
        print(f"[STREAM_ENDPOINT] Stream target content-length: {content_length_str}")

        # SAFETY CHECK: Block HTML wrappers and files smaller than 2MB (2,000,000 bytes)
        if 'text/html' in content_type or (0 < content_length < 2000000):
            print(f"[STREAM_ENDPOINT] ERROR: Blocked invalid upstream response! Content-Type: {content_type}, Size: {content_length} bytes.")
            return jsonify({
                'success': False,
                'error': 'Upstream link expired or returned an ad wrapper. Please try generating the download link again.'
            }), 400

        def generate():
            chunk_count = 0
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    chunk_count += 1
                    yield chunk
            print(f"[STREAM_ENDPOINT] Stream finished successfully. Total chunks sent: {chunk_count}")

        final_content_type = r.headers.get('content-type', 'audio/mpeg' if fmt == 'mp3' else 'video/mp4')
        headers = {
            'Content-Disposition': f'attachment; filename="{clean_title}.{ext}"',
            'Content-Type': final_content_type
        }
        if 'content-length' in r.headers:
            headers['Content-Length'] = r.headers['content-length']

        return Response(generate(), headers=headers)
    except Exception as e:
        print(f"[STREAM_ENDPOINT] Streaming failed with exception: {str(e)}")
        return 'Streaming failed', 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f"[SERVER] Starting Flask server on port {port}...")
    app.run(host='0.0.0.0', port=port)

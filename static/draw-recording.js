(() => {
  const root = document.querySelector('[data-submission-draw]');
  if (!root) return;
  const start = root.querySelector('[data-record-draw]');
  const stop = root.querySelector('[data-stop-recording]');
  const download = root.querySelector('[data-download-recording]');
  const status = root.querySelector('[data-recording-status]');
  const celebration = document.querySelector('[data-draw-celebration]');
  const controls = start.closest('.draw-recording-controls');
  root.before(controls);
  let recorder, stream, outputStream, captureVideo, videoUrl, finishTimer, paintFrame;
  const captureHandle = `cl-draw-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const supported = Boolean(navigator.mediaDevices?.getDisplayMedia && navigator.mediaDevices?.setCaptureHandleConfig && window.MediaRecorder && HTMLCanvasElement.prototype.captureStream);
  if (supported) navigator.mediaDevices.setCaptureHandleConfig({handle: captureHandle, permittedOrigins: [location.origin]});
  start.disabled = !supported;
  if (!supported) status.textContent = 'Tab recording is unavailable in this browser. Use a desktop browser with screen sharing support.';
  function stopRecording() {
    clearTimeout(finishTimer);
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }
  function cleanUp() {
    cancelAnimationFrame(paintFrame);
    stream?.getTracks().forEach(track => track.stop());
    outputStream?.getTracks().forEach(track => track.stop());
    if (captureVideo) { captureVideo.pause(); captureVideo.srcObject = null; }
    stream = null;
    stop.hidden = true;
    start.disabled = !supported;
    document.body.classList.remove('draw-recording-mode');
  }
  start.addEventListener('click', async () => {
    start.disabled = true;
    document.body.classList.add('draw-recording-mode');
    root.scrollIntoView({block: 'start'});
    status.textContent = 'Choose this browser tab in the sharing window. Audio is not recorded.';
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({video: {frameRate: 30}, audio: false, preferCurrentTab: true});
      const track = stream.getVideoTracks()[0];
      if (track.getSettings().displaySurface !== 'browser' || track.getCaptureHandle?.()?.handle !== captureHandle) {
        throw new Error('Choose this tab to record only the giveaway section.');
      }
      captureVideo = document.createElement('video');
      captureVideo.muted = true;
      captureVideo.playsInline = true;
      captureVideo.srcObject = stream;
      await captureVideo.play();
      const canvas = document.createElement('canvas');
      canvas.width = 1280;
      canvas.height = 720;
      const context = canvas.getContext('2d', {alpha: false});
      function paint() {
        context.fillStyle = '#10213f';
        context.fillRect(0, 0, canvas.width, canvas.height);
        // The source tab is never recorded directly: only these bounded regions
        // are copied into the output video, with letterboxing to avoid stretching.
        const target = celebration?.open ? celebration : root;
        const rect = target.getBoundingClientRect();
        const left = Math.max(0, rect.left);
        const top = Math.max(0, rect.top);
        const width = Math.min(innerWidth, rect.right) - left;
        const height = Math.min(innerHeight, rect.bottom) - top;
        if (width > 0 && height > 0 && captureVideo.readyState >= 2) {
          const scaleX = captureVideo.videoWidth / innerWidth;
          const scaleY = captureVideo.videoHeight / innerHeight;
          const fit = Math.min(canvas.width / width, canvas.height / height);
          context.drawImage(captureVideo, left * scaleX, top * scaleY, width * scaleX, height * scaleY,
            (canvas.width - width * fit) / 2, (canvas.height - height * fit) / 2, width * fit, height * fit);
        }
        paintFrame = requestAnimationFrame(paint);
      }
      paint();
      outputStream = canvas.captureStream(30);
      const mimeType = ['video/mp4', 'video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(type => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(outputStream, mimeType ? {mimeType} : undefined);
      const chunks = [];
      recorder.addEventListener('dataavailable', event => { if (event.data.size) chunks.push(event.data); });
      recorder.addEventListener('stop', () => {
        const type = recorder.mimeType || chunks[0]?.type || 'video/webm';
        cleanUp();
        if (!chunks.length) { status.textContent = 'No video was captured. Try recording again.'; return; }
        if (videoUrl) URL.revokeObjectURL(videoUrl);
        videoUrl = URL.createObjectURL(new Blob(chunks, {type}));
        download.href = videoUrl;
        download.download = `CL-Paints-giveaway-${new Date().toISOString().slice(0, 10)}.${type.includes('mp4') ? 'mp4' : 'webm'}`;
        download.hidden = false;
        status.textContent = 'Video ready. Download it to review and share on social media.';
      });
      recorder.addEventListener('error', () => { stopRecording(); cleanUp(); status.textContent = 'Recording failed. Any captured video will be offered for download.'; });
      stream.getVideoTracks()[0].addEventListener('ended', stopRecording);
      recorder.start(1000);
      stop.hidden = false;
      download.hidden = true;
      status.textContent = 'Recording — pull the handle to run the draw. Recording stops 8 seconds after the winner appears.';
    } catch (error) {
      cleanUp();
      status.textContent = error.message === 'Choose this tab to record only the giveaway section.' ? error.message : 'Recording was not started. You can try again or run the draw without recording.';
    }
  });
  root.addEventListener('draw:winner', () => {
    if (recorder?.state === 'recording') finishTimer = setTimeout(stopRecording, 8000);
  });
  celebration?.addEventListener('close', stopRecording);
  stop.addEventListener('click', stopRecording);
  window.addEventListener('pagehide', () => {
    stopRecording();
    stream?.getTracks().forEach(track => track.stop());
    if (videoUrl) URL.revokeObjectURL(videoUrl);
  });
})();

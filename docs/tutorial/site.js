const status = document.getElementById('copy-status');
let timeout;
document.addEventListener('click', async (event) => {
  const copy = event.target.closest('[data-copy]');
  if (copy) {
    const text = copy.closest('.field-content').querySelector('.field-value').textContent;
    try {
      await navigator.clipboard.writeText(text);
      status.textContent = 'Field value copied';
    } catch {
      const range = document.createRange();
      range.selectNodeContents(copy.closest('.field-content').querySelector('.field-value'));
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
      status.textContent = 'Text selected. Use Ctrl+C or Command+C to copy.';
    }
    clearTimeout(timeout); timeout = setTimeout(() => status.textContent = '', 4000);
  }
  if (event.target.closest('[data-print]')) window.print();
});

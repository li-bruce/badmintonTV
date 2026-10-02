(() => {
  const search = document.querySelector('#doc-search');
  const chapters = [...document.querySelectorAll('.chapter')];
  const texts = chapters.map(chapter => chapter.textContent.toLocaleLowerCase());
  const count = document.querySelector('#search-count');
  const empty = document.querySelector('#empty-result');
  const filter = () => {
    const query = search.value.trim().toLocaleLowerCase();
    let matches = 0;
    chapters.forEach((chapter, index) => {
      const visible = !query || texts[index].includes(query);
      chapter.hidden = !visible;
      if (visible) matches++;
    });
    count.textContent = query ? `${matches} 个章节` : '';
    empty.hidden = matches !== 0;
  };
  search.addEventListener('input', filter);
  document.querySelectorAll('a[href^="#"]').forEach(link => link.addEventListener('click', () => {
    if (search.value) {search.value = ''; filter();}
  }));
  document.querySelector('#print-button').addEventListener('click', () => window.print());
  const toggle = document.querySelector('.menu-toggle');
  const sidebar = document.querySelector('.sidebar');
  toggle.addEventListener('click', () => {
    const open = sidebar.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {sidebar.classList.remove('open'); toggle.setAttribute('aria-expanded','false');}
  });
  document.querySelector('main').addEventListener('click', () => {
    sidebar.classList.remove('open'); toggle.setAttribute('aria-expanded','false');
  });
})();

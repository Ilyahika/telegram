/* QWE Mini App — единственный JavaScript-файл.
 * Важно: никогда не доверяйте user.id из браузера без проверки initData сервером.
 */
const tg = window.Telegram?.WebApp;
const splash = document.getElementById('splash');
const page = document.getElementById('app');

// Показывает страницу и скрывает заставку; ограничение времени — только визуальный эффект.
function showPage() {
  page.classList.remove('is-hidden');
  splash.classList.add('is-gone');
}

function showProfile(player) {
  // textContent безопасно вставляет имя как текст, а не как HTML
  document.getElementById('player-name').textContent = player.display_name || 'Игрок';
  document.getElementById('player-subtitle').textContent = `Telegram ID: ${player.telegram_id}`;
  const letter = (player.display_name || 'Q').trim().charAt(0).toUpperCase();
  document.getElementById('avatar-letter').textContent = letter;
  // Для первой версии не подгружаем произвольную ссылку на аватар — меньше внешних запросов.
}

async function initializeApp() {
  const started = Date.now();
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor?.('#09081a');
    tg.setBackgroundColor?.('#09081a');
  }

  if (!tg?.initData) {
    // В обычном браузере нет подписанных Telegram-данных.
    document.getElementById('player-subtitle').textContent = 'Открой QWE через Telegram-бота';
  } else {
    try {
      const response = await fetch('/api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: tg.initData })
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      showProfile(data.player);
    } catch (error) {
      console.error('QWE login:', error);
      document.getElementById('player-subtitle').textContent = 'Не удалось загрузить профиль — попробуй открыть снова';
    }
  }

  // Держим заставку минимум 2 секунды, чтобы анимацию было видно.
  const wait = Math.max(0, 2000 - (Date.now() - started));
  await new Promise(resolve => setTimeout(resolve, wait));
  showPage();
}

initializeApp();

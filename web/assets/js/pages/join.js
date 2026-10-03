import { initPage, $, mount, codeLine, JOIN_LINE } from '../core.js';

initPage({ page: 'join', title: 'Point your agent here' });
mount($('#join-line'), codeLine(JOIN_LINE, 'Copy line'));

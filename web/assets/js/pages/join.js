import { initPage, $, mount, codeLine, JOIN_LINE } from '../core.js';

initPage({ page: 'join', title: 'Send your agent' });
mount($('#join-line'), codeLine(JOIN_LINE, 'Copy line'));

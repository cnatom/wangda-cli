// 最小 DOM 桩：只用于验证 engine.SUBJECT_ITEMS 在「无 .study-status 的专区卡片」上不抛错。
// 用法：node tests/subject_items_stub.js "<SUBJECT_ITEMS 表达式>"，结果以 JSON 打到 stdout。
const expr = process.argv[2];
const nodes = [];

function node(props = {}) {
  return Object.assign({
    innerText: '', className: '',
    classList: {contains: () => false},
    getAttribute: () => null,
    querySelector: () => null,
    parentElement: null,
  }, props);
}

function card({id, type, status, optional, action, body}) {
  const anchor = node({
    innerText: action || '开始学习',
    getAttribute: name => (name === 'data-resource-id' ? id : name === 'data-section-type' ? type : null),
  });
  const wrapper = node({
    innerText: body || '',
    querySelector: sel => {
      if (sel === '.study-status') return status ? node({innerText: status}) : null;
      if (sel === '.required-tag') return optional ? node({innerText: '选修'}) : null;
      return null;
    },
  });
  anchor.parentElement = wrapper;
  nodes.push(anchor);
}

// 标准卡片：有 .study-status
card({id: 'std-1', type: '10', status: '已完成', body: '标准课程卡片 已完成'});
// 专区卡片：没有 .study-status，只有按钮与说明文字（法治思想专区就是这个布局）
card({id: 'zone-1', type: '10', action: '开始学习', body: '视频来源于央视网\n开始学习'});
// 选修卡片：带 .required-tag
card({id: 'opt-1', type: '10', status: '未开始', optional: true, body: '选修课程 未开始'});

global.document = {
  querySelectorAll: sel => (sel === 'a[data-resource-id]' ? nodes : []),
  body: {innerText: '完成 1 项 / 共 3 项'},
};

process.stdout.write(String(eval(expr)));

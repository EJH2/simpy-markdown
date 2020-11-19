import re
from typing import Union, Callable, Iterable, Optional
from urllib.parse import unquote

from functools import cmp_to_key

import numbers

CR_NEWLINE_R = re.compile(r'\r\n?')
TAB_R = re.compile(r'\t')
FORMFEED_R = re.compile(r'\f')


def preprocess(source: str) -> str:
    return TAB_R.sub('\n', FORMFEED_R.sub('', CR_NEWLINE_R.sub('    ', source)))


def populate_initial_state(state: dict = {}, default_state: dict = None) -> dict:
    if default_state:
        for key in default_state:
            state[key] = default_state[key]
    return state


def parser_for(rules: dict, default_state: dict = {}) -> \
        Callable[[str, Optional[dict]], Callable[[str, Optional[dict]], list]]:

    def filter_rules(rule_type):
        rule = rules.get(rule_type)
        if not rule or not hasattr(rule, 'match'):
            return False
        order = rule.order
        if not isinstance(order, numbers.Number):
            print(f'Invalid order for rule `{rule_type}`: {order}')
        return True

    rule_list = list(filter(filter_rules, rules.keys()))

    def sort_rules(rule_type_a, rule_type_b):
        rule_a = rules[rule_type_a]
        rule_b = rules[rule_type_b]
        order_a = rule_a.order
        order_b = rule_b.order

        if order_a != order_b:
            return order_a - order_b

        secondary_order_a = 0 if hasattr(rule_a, 'quality') else 1
        secondary_order_b = 0 if hasattr(rule_b, 'quality') else 1

        if secondary_order_a != secondary_order_b:
            return secondary_order_a - secondary_order_b
        elif rule_type_a < rule_type_b:
            return -1
        elif rule_type_a > rule_type_b:
            return 1
        else:
            return 0

    rule_list.sort(key=cmp_to_key(sort_rules))

    latest_state = None

    def nested_parse(source: str, state: dict = None):
        result = []
        nonlocal latest_state
        global current_order
        state = state or latest_state
        latest_state = state
        while source:
            rule_type = None
            rule = None
            capture = None
            quality = -1

            i = 0
            current_rule_type = rule_list[0]
            current_rule = rules[current_rule_type]

            while not i or (
                    current_rule and (not capture or (
                    current_rule.order == current_order and hasattr(current_rule, 'quality')))
            ):
                current_order = current_rule.order
                previous_capture_string = "" if state.get('previous_capture') is None else state['previous_capture'][0]
                current_capture = current_rule.match(source, state, previous_capture_string)

                if current_capture:
                    current_quality = current_rule.quality(
                        current_capture, state, previous_capture_string
                    ) if hasattr(current_rule, 'quality') else 0
                    if not (current_quality <= quality):
                        rule_type = current_rule_type
                        rule = current_rule
                        capture = current_capture
                        quality = current_quality

                i += 1
                try:
                    current_rule_type = rule_list[i]
                    current_rule = rules[current_rule_type]
                except IndexError:
                    current_rule = None

            if rule is None or capture is None:
                raise Exception(
                    "Could not find a matching rule for the below " +
                    "content. The rule with highest `order` should " +
                    "always match content provided to it. Check " +
                    "the definition of `match` for '" +
                    rule_list[len(rule_list) - 1] +
                    "'. It seems to not match the following source:\n" +
                    source)
            if capture.pos:
                raise Exception(
                    "`match` must return a capture starting at index 0 " +
                    "(the current parse index). Did you forget a ^ at the " +
                    "start of the RegExp?"
                )

            parsed = rule.parse(capture, nested_parse, state)

            if isinstance(parsed, list):
                result.append(parsed)
            else:
                if parsed.get('type') is None:
                    parsed['type'] = rule_type
                result.append(parsed)

            state['previous_capture'] = capture
            source = source[len(state['previous_capture'][0]):]

        return result

    def outer_parse(source: str, state: dict = None):
        nonlocal latest_state
        latest_state = populate_initial_state(state, default_state)
        if not latest_state.get('inline') and not latest_state.get('disable_auto_block_newlines'):
            source = source + '\n\n'

        latest_state['previous_capture'] = None
        return nested_parse(preprocess(source), latest_state)

    return outer_parse


def inline_regex(regex: str) -> Callable[[str, dict], Union[Iterable, None]]:

    def match(source, state, *args, **kwargs):
        if state.get('inline'):
            return re.match(regex, source)
        else:
            return None

    match.regex = regex
    return match


def block_regex(regex: str) -> Callable[[str, dict], Union[Iterable, None]]:

    def match(source, state, *args, **kwargs):
        if state.get('inline'):
            return None
        else:
            return re.match(regex, source)

    match.regex = regex
    return match


def any_scope_regex(regex: str) -> Callable[[str, dict], Iterable]:

    def match(source, state, *args, **kwargs):
        return re.match(regex, source)

    match.regex = regex
    return match


def react_element(_type: str, key: Union[str, int] = None, props: dict = {}) -> dict:
    element = {
        'type': _type,
        'key': key,
        'ref': None,
        'props': props,
        '_owner': None
    }
    return element


def html_tag(tag_name: str, content: str, attributes: dict = {}, is_closed: bool = True) -> str:
    attribute_string = ''
    for attr in attributes:
        if attribute := attributes[attr]:
            attribute_string += f' {sanitize_text(attr)}="{sanitize_text(attribute)}"'

    unclosed_tag = f'<{tag_name}{attribute_string}>'
    if is_closed:
        return unclosed_tag + content + f'</{tag_name}>'
    else:
        return unclosed_tag


EMPTY_PROPS = {}


def sanitize_url(url: str = None) -> Union[str, None]:
    if not url:
        return None

    try:
        prot = re.sub(r'[^A-Za-z0-9/:]', '', unquote(url)).lower()
        if any([prot.startswith('javascript:'), prot.startswith('vbscript:'), prot.startswith('data:')]):
            return None
    except:
        return None
    return url


SANITIZE_TEXT_R = re.compile('[<>&"\']')
SANITIZE_TEXT_CODES = {
    '<': '&lt;',
    '>': '&gt;',
    '&': '&amp;',
    '"': '&quot;',
    "'": '&#x27;',
    '/': '&#x2F;',
    "`": '&#96;'
}


def sanitize_text(text):
    return SANITIZE_TEXT_R.sub(lambda m: SANITIZE_TEXT_CODES[m.group()], str(text))


UNESCAPE_URL_R = re.compile(r'\\([^0-9A-Za-z\s])')


def unescape_url(raw_url_string: str):
    return UNESCAPE_URL_R.sub(lambda m: m.group(1), raw_url_string)


def parse_inline(parse, content: str, state: dict):
    is_currently_inline = state.get('inline', False)
    state['inline'] = True
    result = parse(content, state)
    state['inline'] = is_currently_inline
    return result


def parse_block(parse, content, state):
    is_currently_inline = state.get('inline', False)
    state['inline'] = False
    result = parse(content + '\n\n', state)
    state['inline'] = is_currently_inline
    return result


def parse_capture_inline(capture, parse, state):
    return {
        'content': parse_inline(parse, capture[1], state)
    }


def ignore_capture():
    return {}


LIST_BULLET = "(?:[*+-]|\d+\.)"
LIST_ITEM_PREFIX = "( *)(" + LIST_BULLET + ") +"
LIST_ITEM_PREFIX_R = re.compile("^" + LIST_ITEM_PREFIX)
LIST_ITEM_R = re.compile(
    LIST_ITEM_PREFIX +
    "[^\\n]*(?:\\n" +
    "(?!\\1" + LIST_BULLET + " )[^\\n]*)*(\n|$)",
    re.MULTILINE
)
BLOCK_END_R = re.compile(r'\n{2,}$')
INLINE_CODE_ESCAPE_BACKTICKS_R = re.compile(r'^ (?= *`)|(` *) $')
LIST_BLOCK_END_R = BLOCK_END_R
LIST_ITEM_END_R = re.compile(r' *\n+$')
LIST_R = re.compile(
    "^( *)(" + LIST_BULLET + ") " +
    "[\\s\\S]+?(?:\n{2,}(?! )" +
    "(?!\\1" + LIST_BULLET + " )\n*" +
    "|\\s*\n*$)"
)
LIST_LOOKBEHIND_R = re.compile(r'(?:^|\n)( *)$')


def TABLES():
    TABLE_ROW_SEPARATOR_TRIM = re.compile(r'^ *\| *| *\| *$')
    TABLE_CELL_END_TRIM = re.compile(r' *$')
    TABLE_RIGHT_ALIGN = re.compile('^ *-+: *$')
    TABLE_CENTER_ALIGN = re.compile('^ *:-+: *$')
    TABLE_LEFT_ALIGN = re.compile('^ *:-+ *$')

    def parse_table_align_capture(align_capture):
        if TABLE_RIGHT_ALIGN.match(align_capture):
            return "right"
        elif TABLE_CENTER_ALIGN.match(align_capture):
            return "center"
        elif TABLE_LEFT_ALIGN.match(align_capture):
            return "left"
        else:
            return None

    def parse_table_align(source, parse, state, trim_end_separators):
        if trim_end_separators:
            source = TABLE_ROW_SEPARATOR_TRIM.sub("", source)
        align_text = source.strip().split("|")
        return list(map(parse_table_align_capture, align_text))

    def parse_table_row(source, parse, state, trim_end_separators):
        prev_in_table = state.get('in_table')
        state['in_table'] = True
        table_row = parse(source.strip(), state)
        state['in_table'] = prev_in_table

        cells = [[]]
        for index, node in enumerate(table_row):
            if node['type'] == 'table_separator':
                if not trim_end_separators or index != 0 and index != len(table_row) - 1:
                    cells.append([])
            else:
                if node['type'] == 'text' and (
                        table_row[index + 1]['type'] == 'table_separator'
                ) if len(table_row) > index + 1 else None:
                    node['content'] = TABLE_CELL_END_TRIM.sub("", node['content'], count=1)
                cells[len(cells) - 1].append(node)

        return cells

    def parse_table_cells(source, parse, state, trim_end_separators):
        rows_text = source.strip().split("\n")

        return list(map(lambda row_text: parse_table_row(row_text, parse, state, trim_end_separators), rows_text))

    def parse_table(trim_end_separators):

        def inner(capture, parse, state):
            state['inline'] = True
            header = parse_table_row(capture[1], parse, state, trim_end_separators)
            align = parse_table_align(capture[2], parse, state, trim_end_separators)
            cells = parse_table_cells(capture[3], parse, state, trim_end_separators)
            state['inline'] = False

            return {
                'type': "table",
                'header': header,
                'align': align,
                'cells': cells
            }

        return inner

    return {
        'parse_table': parse_table(True),
        'parse_np_table': parse_table(False),
        'TABLE_REGEX': re.compile(r'^ *(\|.+)\n *\|( *[-:]+[-| :]*)\n((?: *\|.*(?:\n|$))*)\n*'),
        'NPTABLE_REGEX': re.compile(r'^ *(\S.*\|.*)\n *([-:]+ *\|[-| :]*)\n((?:.*\|.*(?:\n|$))*)\n*')
    }


LINK_INSIDE = "(?:\\[[^\\]]*\\]|[^\\[\\]]|\\](?=[^\\[]*\\]))*"
LINK_HREF_AND_TITLE = "\\s*<?((?:\\([^)]*\\)|[^\\s\\\\]|\\\\.)*?)>?(?:\\s+['\"]([\\s\\S]*?)['\"])?\\s*"
AUTOLINK_MAILTO_CHECK_R = re.compile('mailto:', re.IGNORECASE)


def parse_ref(capture, state, ref_node):
    ref = re.sub(r'\s+', ' ', capture[2] or capture[1]).lower()

    if state.get('_defs') and state['_defs'].get(ref):
        _def = state['_defs'][ref]
        ref_node['target'] = _def['target']
        ref_node['title'] = _def['title']

    state['_refs'] = state.get('_refs', {})
    state['_refs'][ref] = state['_refs'].get(ref, [])
    state['_refs'][ref].append(ref_node)

    return ref_node


current_order = 0


class Rule:
    def __init__(self, order):
        self.order = order

    def match(self, *args, **kwargs):
        pass

    def parse(self, capture, parse, state):
        pass

    def react(self, node, output, state):
        pass

    def html(self, node, output, state):
        pass


class Array(Rule):

    def react(self, arr, output, state):
        old_key = state['key']
        result = []

        i = 0
        key = 0
        while i < len(arr):
            state['key'] = str(i)

            node = arr[i]
            if node['type'] == 'text':
                node = {'type': 'text', 'content': node['content']}
                while i + 1 < len(arr) and arr[i + 1]['type'] == 'text':
                    node['content'] += arr[i + 1]['content']
                    i += 1

            result.append(output(node, state))
            key += 1

        state['key'] = old_key
        return result

    def html(self, arr, output, state):
        result = ''

        i = 0
        while i < len(arr):
            node = arr[i]
            if node['type'] == 'text':
                node = {'type': 'text', 'content': node['content']}
                while i + 1 < len(arr) and arr[i + 1]['type'] == 'text':
                    node['content'] += arr[i + 1]['content']
                    i += 1
            i += 1

            result += output(node, state)

        return result


class Heading(Rule):

    def match(self, *args, **kwargs):
        return block_regex(r'^ *(#{1,6})([^\n]+?)#* *(?:\n *)+\n')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return {
            'level': len(capture[1]),
            'content': parse_inline(parse, capture[2].strip(), state)
        }

    def react(self, node, output, state):
        return react_element(
            'h' + node['level'],
            state['key'],
            {
                'children': output(node['content'], state)
            }
        )

    def html(self, node, output, state):
        return html_tag('h' + str(node['level']), output(node['content'], state))


class NpTable(Rule):

    def match(self, *args, **kwargs):
        return block_regex(TABLES()['NPTABLE_REGEX'])(*args, **kwargs)

    def parse(self, capture, parse, state):
        return TABLES()['parse_np_table'](capture, parse, state)


class LHeading(Rule):

    def match(self, *args, **kwargs):
        return block_regex(r'^([^\n]+)\n *(=|-){3,} *(?:\n *)+\n')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return {
            'type': 'heading',
            'level': 1 if capture[2] == '=' else 2,
            'content': parse_inline(parse, capture[1], state)
        }


class HR(Rule):

    def match(self, *args, **kwargs):
        return block_regex(r'^( *[-*_]){3,} *(?:\n *)+\n')(*args, **kwargs)

    def parse(self, *args, **kwargs):
        return ignore_capture()

    def react(self, node, output, state):
        return react_element(
            'hr',
            state['key'],
            EMPTY_PROPS
        )

    def html(self, node, output, state):
        return '<hr>'


class CodeBlock(Rule):

    def match(self, *args, **kwargs):
        return block_regex(r'^(?:    [^\n]+\n*)+(?:\n *)+\n')(*args, **kwargs)

    def parse(self, capture, parse, state):
        content = re.sub(r'\n+$', '', re.sub(r'^    ', '', capture[0]))
        return {
            'lang': None,
            'content': content
        }

    def react(self, node, output, state):
        class_name = f'markdown-code-{node["lang"]}' if node['lang'] else None

        return react_element(
            'pre',
            state['key'],
            {
                'children': react_element(
                    'code',
                    None,
                    {
                        'className': class_name,
                        'children': node['content']
                    }
                )
            }
        )

    def html(self, node, output, state):
        class_name = f'markdown-code-{node["lang"]}' if node['lang'] else None

        code_block = html_tag('code', sanitize_text(node['content']), {
            'class': class_name
        })
        return html_tag('pre', code_block)


class Fence(Rule):

    def match(self, *args, **kwargs):
        return block_regex(r'^ *(`{3,}|~{3,}) *(?:(\S+) *)?\n([\s\S]+?)\n?\1 *(?:\n *)+\n')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return {
            'type': 'codeBlock',
            'lang': capture[2] or None,
            'content': capture[3]
        }


class BlockQuote(Rule):

    def match(self, *args, **kwargs):
        return block_regex(r'^( *>[^\n]+(\n[^\n]+)*\n*)+\n{2,}')(*args, **kwargs)

    def parse(self, capture, parse, state):
        content = re.sub(r'^ *> ?', '', capture[0])

        return {
            'content': parse(content, state)
        }

    def react(self, node, output, state):
        return react_element(
            'blockquote',
            state['key'],
            {
                'children': output(node['content'], state)
            }
        )

    def html(self, node, output, state):
        return html_tag('blockquote', output(node['content'], state))


class List(Rule):

    def match(self, source, state, *args, **kwargs):
        previous_capture_string = '' if state.get('previous_capture') is None else state['previous_capture'][0]
        is_start_of_line_capture = LIST_LOOKBEHIND_R.match(previous_capture_string)
        is_list_block = state.get('_list') or not state.get('inline')

        if is_start_of_line_capture and is_list_block:
            source = is_start_of_line_capture[1] + source
            a = LIST_R.match(source)
            return a
        else:
            return None

    def parse(self, capture, parse, state):
        bullet = capture[2]
        ordered = len(bullet) > 1
        start = int(re.sub(r'[^\d]+?', '', bullet)) if ordered else None
        items = list(LIST_ITEM_R.finditer(LIST_BLOCK_END_R.sub('\n', capture[0], count=1)))

        last_item_was_a_paragraph = False

        def content_map(i, item):
            item = item[0]
            prefix_capture = LIST_ITEM_PREFIX_R.match(item)
            space = len(prefix_capture[0]) if prefix_capture else 0
            space_regex = r'^ {1,' + str(space) + '}'
            content = LIST_ITEM_PREFIX_R.sub('', re.sub(space_regex, '', item, re.MULTILINE), count=1)

            is_last_item = i == len(list(items)) - 1
            contains_blocks = '\n\n' in content

            nonlocal last_item_was_a_paragraph
            this_item_is_a_paragraph = contains_blocks or (is_last_item and last_item_was_a_paragraph)
            last_item_was_a_paragraph = this_item_is_a_paragraph

            old_state_inline = state.get('inline')
            old_state_list = state.get('_list')
            state['_list'] = True

            if this_item_is_a_paragraph:
                state['inline'] = False
                adjusted_content = LIST_ITEM_END_R.sub('\n\n', content, count=1)
            else:
                state['inline'] = True
                adjusted_content = LIST_ITEM_END_R.sub('', content, count=1)

            result = parse(adjusted_content, state)

            state['inline'] = old_state_inline
            state['_list'] = old_state_list
            return result

        item_content = list(map(lambda enum: content_map(enum[0], enum[1]), enumerate(items)))

        return {
            'ordered': ordered,
            'start': start,
            'items': item_content
        }

    def react(self, node, output, state):
        list_wrapper = 'ol' if node['ordered'] else 'ul'

        return react_element(
            list_wrapper,
            state['key'],
            {
                'start': node['start'],
                'children': list(map(lambda index, item: react_element(
                    'li',
                    str(index),
                    {
                        'children': output(item, state)
                    }
                ), node['items']))
            }
        )

    def html(self, node, output, state):
        list_items = ''.join([html_tag('li', output(item, state)) for item in node['items']])

        list_tag = 'ol' if node['ordered'] else 'ul'
        attributes = {
            'start': node['start']
        }
        return html_tag(list_tag, list_items, attributes)


class Def(Rule):

    def match(self, *args, **kwargs):
        m = block_regex(r'^ *\[([^\]]+)\]: *<?([^\s>]*)>?(?: +["(]([^\n]+)[")])? *\n(?: *\n)*')(*args, **kwargs)
        return m

    def parse(self, capture, parse, state):
        _def = re.sub(r'\s+', ' ', capture[1]).lower()
        target = capture[2]
        title = capture[3]

        if state.get('_refs') and state['_refs'].get(_def):
            for ref_node in state['_refs'][_def]:
                ref_node['target'] = target
                ref_node['title'] = title

        state['_defs'] = state.get('_defs', {})
        state['_defs'][_def] = {
            'target': target,
            'title': title
        }

        return {
            'def': _def,
            'target': target,
            'title': title
        }

    def react(self, *args, **kwargs):
        return

    def html(self, *args, **kwargs):
        return ''


class Table(Rule):

    def match(self, *args, **kwargs):
        return block_regex(TABLES()['TABLE_REGEX'])(*args, **kwargs)

    def parse(self, capture, parse, state):
        return TABLES()['parse_table'](capture, parse, state)

    def react(self, node, output, state):

        def get_style(column_index):
            return {} if not node['align'][column_index] else {
                'textAlign': node['align'][column_index]
            }

        headers = [react_element(
            'th',
            str(index),
            {
                'style': get_style(index),
                'scope': 'col',
                'children': output(content, state)
            }
        ) for index, content in enumerate(node['header'])]

        rows = [react_element(
            'tr',
            str(row_index),
            {
                'children': [react_element(
                    'td',
                    str(column_index),
                    {
                        'style': get_style(column_index),
                        'children': output(content, state)
                    }
                ) for column_index, content in enumerate(row)]
            }
        ) for row_index, row in enumerate(node['cells'])]

        return react_element(
            'table',
            state['key'],
            {
                'children': [react_element(
                    'thead',
                    'thead',
                    {
                        'children': react_element(
                            'tr',
                            None,
                            {
                                'children': headers
                            }
                        )
                    }
                ), react_element(
                    'tbody',
                    'tbody',
                    {
                        'children': rows
                    }
                )]
            }
        )

    def html(self, node, output, state):

        def get_style(column_index):
            return '' if not node['align'][column_index] else 'text-align:' + node['align'][column_index] + ';'

        headers = ''.join([
            html_tag(
                'th',
                output(
                    content,
                    state
                ),
                {
                    'style': get_style(index),
                    'scope': 'col'
                }
            ) for index, content in enumerate(node['header'])
        ])

        rows = ''.join([html_tag(
            'tr',
            ''.join([html_tag(
                'td',
                output(content, state),
                {
                    'style': get_style(column_index)
                }
            ) for column_index, content in enumerate(row)])
        ) for row in node['cells']])

        thead = html_tag('thead', html_tag('tr', headers))
        tbody = html_tag('tbody', rows)

        return html_tag('table', thead + tbody)


class NewLine(Rule):

    def match(self, *args, **kwargs):
        return block_regex(r'^(?:\n *)*\n')(*args, **kwargs)

    def parse(self, *args, **kwargs):
        return ignore_capture()

    def react(self, node, output, state):
        return '\n'

    def html(self, node, output, state):
        return '\n'


class Paragraph(Rule):

    def match(self, *args, **kwargs):
        return block_regex(r'^((?:[^\n]|\n(?! *\n))+)(?:\n *)+\n')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return parse_capture_inline(capture, parse, state)

    def react(self, node, output, state):
        return react_element(
            'div',
            state['key'],
            {
                'className': 'paragraph',
                'children': output(node['content'], state)
            }
        )

    def html(self, node, output, state):
        attributes = {
            'class': 'paragraph'
        }
        return html_tag('div', output(node['content'], state), attributes)


class Escape(Rule):

    def match(self, *args, **kwargs):
        return inline_regex(r'^\\([^0-9A-Za-z\s])')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return {
            'type': 'text',
            'content': capture[1]
        }


class TableSeparator(Rule):

    def match(self, source, state, *args, **kwargs):
        if not state.get('in_table'):
            return

        return re.match(r'^ *\| *', source)

    def parse(self, *args, **kwargs):
        return {
            'type': 'table_separator'
        }

    def react(self, *args, **kwargs):
        return ' | '

    def html(self, *args, **kwargs):
        return ' &vert; '


class AutoLink(Rule):

    def match(self, *args, **kwargs):
        return inline_regex(r'^<([^: >]+:\/[^ >]+)>')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return {
            'type': 'link',
            'content': [{
                'type': 'text',
                'content': capture[1]
            }],
            'target': capture[1]
        }


class MailTo(Rule):

    def match(self, *args, **kwargs):
        return inline_regex(r'^<([^ >]+@[^ >]+)>')(*args, **kwargs)

    def parse(self, capture, parse, state):
        address = capture[1]
        target = capture[1]

        if not AUTOLINK_MAILTO_CHECK_R.match(target):
            target = f'mailto:{target}'

        return {
            'type': 'link',
            'content': [{
                'type': 'text',
                'content': address
            }],
            'target': target
        }


class URL(Rule):

    def match(self, *args, **kwargs):
        return inline_regex(r'^(https?:\/\/[^\s<]+[^<.,:;"\')\]\s])')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return {
            'type': 'link',
            'content': [{
                'type': 'text',
                'content': capture[1]
            }],
            'target': capture[1],
            'title': None
        }


class Link(Rule):

    def match(self, *args, **kwargs):
        return inline_regex('^\\[(' + LINK_INSIDE + ')\\]\\(' + LINK_HREF_AND_TITLE + '\\)')(*args, **kwargs)

    def parse(self, capture, parse, state):
        link = {
            'content': parse(capture[1], state),
            'target': unescape_url(capture[2]),
            'title': capture[3]
        }
        return link

    def react(self, node, output, state):
        return react_element(
            'a',
            state['key'],
            {
                'href': sanitize_text(node['target']),
                'title': node['title'],
                'children': output(node['content'], state)
            }
        )

    def html(self, node, output, state):
        attributes = {
            'href': sanitize_text(node['target']),
            'title': node.get('title')
        }

        return html_tag('a', output(node['content'], state), attributes)


class Image(Rule):

    def match(self, *args, **kwargs):
        return inline_regex('^!\\[(' + LINK_INSIDE + ')\\]\\(' + LINK_HREF_AND_TITLE + '\\)')(*args, **kwargs)

    def parse(self, capture, parse, state):
        image = {
            'alt': capture[1],
            'target': unescape_url(capture[2]),
            'title': capture[3]
        }

        return image

    def react(self, node, output, state):
        return react_element(
            'img',
            state['key'],
            {
                'src': sanitize_text(node['target']),
                'alt': node['alt'],
                'title': node['title']
            }
        )

    def html(self, node, output, state):
        attributes = {
            'src': sanitize_text(node['target']),
            'alt': node['alt'],
            'title': node['title']
        }

        return html_tag('img', '', attributes, False)


class RefLink(Rule):

    def match(self, *args, **kwargs):
        return inline_regex('^\\[(' + LINK_INSIDE + ')\\]' + '\\s*\\[([^\\]]*)\\]')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return parse_ref(capture, state, {
            'type': 'link',
            'content': parse(capture[1], state)
        })


class RefImage(Rule):

    def match(self, *args, **kwargs):
        return inline_regex('^!\\[(' + LINK_INSIDE + ')\\]' + '\\s*\\[([^\\]]*)\\]')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return parse_ref(capture, state, {
            'type': 'image',
            'alt': capture[1]
        })


class Em(Rule):

    def match(self, *args, **kwargs):
        return inline_regex(
            "^\\b_((?:__|\\\\[\\s\\S]|[^\\\\_])+?)_\\b|^\\*(?=\\S)((?:\\*\\*|\\\\[\\s\\S]"
            "|\\s+(?:\\\\[\\s\\S]|[^\\s\\*\\\\]|\\*\\*)|[^\\s\\*\\\\])+?)\\*(?!\\*)"
        )(*args, **kwargs)

    def quality(self, capture, *args, **kwargs):
        return len(capture[0]) + 0.2

    def parse(self, capture, parse, state):
        return {
            'content': parse(capture[2] or capture[1], state)
        }

    def react(self, node, output, state):
        return react_element(
            'em',
            state['key'],
            {
                'children': output(node['content'], state)
            }
        )

    def html(self, node, output, state):
        return html_tag('em', output(node['content'], state))


class Strong(Rule):

    def match(self, *args, **kwargs):
        return inline_regex(r'^\*\*((?:\\[\s\S]|[^\\])+?)\*\*(?!\*)')(*args, **kwargs)

    def quality(self, capture, *args, **kwargs):
        return len(capture[0]) + 0.1

    def parse(self, capture, parse, state):
        return parse_capture_inline(capture, parse, state)

    def react(self, node, output, state):
        return react_element(
            'strong',
            state['key'],
            {
                'children': output(node['content'], state)
            }
        )

    def html(self, node, output, state):
        return html_tag('strong', output(node['content'], state))


class U(Rule):

    def match(self, *args, **kwargs):
        return inline_regex(r'^__((?:\\[\s\S]|[^\\])+?)__(?!_)')(*args, **kwargs)

    def quality(self, capture, *args, **kwargs):
        return len(capture[0])

    def parse(self, capture, parse, state):
        return parse_capture_inline(capture, parse, state)

    def react(self, node, output, state):
        return react_element(
            'u',
            state['key'],
            {
                'children': output(node['content'], state)
            }
        )

    def html(self, node, output, state):
        return html_tag('u', output(node['content'], state))


class Del(Rule):

    def match(self, *args, **kwargs):
        return inline_regex(r'^~~(?=\S)((?:\\[\s\S]|~(?!~)|[^\s~]|\s(?!~~))+?)~~')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return parse_capture_inline(capture, parse, state)

    def react(self, node, output, state):
        return react_element(
            'del',
            state['key'],
            {
                'children': output(node['content'], state)
            }
        )

    def html(self, node, output, state):
        return html_tag('del', output(node['content'], state))


class InlineCode(Rule):

    def match(self, *args, **kwargs):
        return inline_regex(r'^(`+)([\s\S]*?[^`])\1(?!`)')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return {
            'content': INLINE_CODE_ESCAPE_BACKTICKS_R.sub(r'\1', capture[2])
        }

    def react(self, node, output, state):
        return react_element(
            'code',
            state['key'],
            {
                'children': node['content']
            }
        )

    def html(self, node, output, state):
        return html_tag('code', sanitize_text(node['content']))


class Br(Rule):

    def match(self, *args, **kwargs):
        return any_scope_regex(r'^ {2,}\n')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return ignore_capture()

    def react(self, node, output, state):
        return react_element(
            'br',
            state['key'],
            EMPTY_PROPS
        )

    def html(self, node, output, state):
        return '<br>'


class Text(Rule):

    def match(self, *args, **kwargs):
        return any_scope_regex(r'^[\s\S]+?(?=[^0-9A-Za-z\s\u00c0-\uffff]|\n\n| {2,}\n|\w+:\S|$)')(*args, **kwargs)

    def parse(self, capture, parse, state):
        return {
            'content': capture[0]
        }

    def react(self, node, output, state):
        return node['content']

    def html(self, node, output, state):
        return sanitize_text(node['content'])


default_rules = {
    'Array': Array(current_order),
    'heading': Heading((current_order := current_order + 1) - 1),
    'nptable': NpTable((current_order := current_order + 1) - 1),
    'lheading': LHeading((current_order := current_order + 1) - 1),
    'hr': HR((current_order := current_order + 1) - 1),
    'codeBlock': CodeBlock((current_order := current_order + 1) - 1),
    'fence': Fence((current_order := current_order + 1) - 1),
    'blockQuote': BlockQuote((current_order := current_order + 1) - 1),
    'list': List((current_order := current_order + 1) - 1),
    'def': Def((current_order := current_order + 1) - 1),
    'table': Table((current_order := current_order + 1) - 1),
    'newline': NewLine((current_order := current_order + 1) - 1),
    'paragraph': Paragraph((current_order := current_order + 1) - 1),
    'escape': Escape((current_order := current_order + 1) - 1),
    'tableSeparator': TableSeparator((current_order := current_order + 1) - 1),
    'autolink': AutoLink((current_order := current_order + 1) - 1),
    'mailto': MailTo((current_order := current_order + 1) - 1),
    'url': URL((current_order := current_order + 1) - 1),
    'link': Link((current_order := current_order + 1) - 1),
    'image': Image((current_order := current_order + 1) - 1),
    'reflink': RefLink((current_order := current_order + 1) - 1),
    'refimage': RefImage((current_order := current_order + 1) - 1),
    'em': Em(current_order),
    'strong': Strong(current_order),
    'u': U((current_order := current_order + 1) - 1),
    'del': Del((current_order := current_order + 1) - 1),
    'inlineCode': InlineCode((current_order := current_order + 1) - 1),
    'br': Br((current_order := current_order + 1) - 1),
    'text': Text((current_order := current_order + 1) - 1)
}


def rules_output(rules, property):
    if not property:
        print('simple-markdown ruleOutput should take \'react\' or \'html\' as the second argument.')

    def nested_rules_output(ast, output_func, state):
        return getattr(rules[ast['type']], property)(ast, output_func, state)

    return nested_rules_output


def react_for(output_func):

    def nested_output(ast, state = {}):
        if isinstance(ast, list):
            old_key = state['key']
            result = []

            last_result = None
            for index, item in enumerate(ast):
                state['key'] = index
                node_out = nested_output(ast[index], state)
                if isinstance(node_out, str) and isinstance(last_result, str):
                    last_result += node_out
                    result[len(result) - 1] = last_result
                else:
                    result.append(node_out)
                    last_result = node_out

            state['key'] = old_key
            return result
        else:
            return output_func(ast, nested_output, state)

    return nested_output


def html_for(output_func):

    def nested_output(ast, state = {}):
        if isinstance(ast, list):
            return ''.join([nested_output(node, state) for node in ast])
        else:
            return output_func(ast, nested_output, state)

    return nested_output


def output_for(rules, property, default_state = {}):
    if not property:
        raise Exception('simple-markdown: outputFor: `property` must be defined. '
                        'if you just upgraded, you probably need to replace `outputFor` with `reactFor`')

    latest_state = None
    array_rule = rules.get('Array') or default_rules['Array']

    array_rule_check = getattr(array_rule, property)
    if not array_rule_check:
        raise Exception(
            'simple-markdown: outputFor: to join nodes of type `' +
            property + '` you must provide an `Array:` joiner rule with that type, ' +
            'Please see the docs for details on specifying an Array rule.'
        )
    array_rule_output = array_rule_check

    def nested_output(ast, state):
        nonlocal latest_state
        state = state or latest_state
        latest_state = state
        if isinstance(ast, list):
            return array_rule_output(ast, nested_output, state)
        else:
            return getattr(rules[ast['type']], property)(ast, nested_output, state)

    def outer_output(ast, state):
        nonlocal latest_state
        latest_state = populate_initial_state(state, default_state)
        return nested_output(ast, latest_state)

    return outer_output


default_raw_parse = parser_for(default_rules)


def default_block_parse(source, state = {}):
    state['inline'] = False
    return default_raw_parse(source, state)


def default_inline_parse(source, state = {}):
    state['inline'] = True
    return default_raw_parse(source, state)


def default_implicit_parse(source, state = {}):
    is_block = BLOCK_END_R.match(source)
    state['inline'] = not is_block
    return default_raw_parse(source, state)


default_react_output = output_for(default_rules, 'react')
default_html_output = output_for(default_rules, 'html')


def markdown_to_react(source, state = {}):
    return default_react_output(default_block_parse(source, state), state)


def markdown_to_html(source, state = {}):
    return default_html_output(default_block_parse(source, state), state)


def ReactMarkdown(props):

    div_props = {}

    for prop in props:
        if prop != 'source' and props.get(prop):
            div_props[prop] = props[prop]

    div_props['children'] = markdown_to_react(props['source'])

    return react_element(
        'div',
        None,
        div_props
    )


if __name__ == '__main__':
    print(default_block_parse("""This is intended as a quick reference and showcase. For more complete info, see [John Gruber's original spec](http://daringfireball.net/projects/markdown/) and the [Github-flavored Markdown info page](http://github.github.com/github-flavored-markdown/).

Note that there is also a [Cheatsheet specific to Markdown Here](./Markdown-Here-Cheatsheet) if that's what you're looking for. You can also check out [more Markdown tools](./Other-Markdown-Tools).

##### Table of Contents  
[Headers](#headers)  
[Emphasis](#emphasis)  
[Lists](#lists)  
[Links](#links)  
[Images](#images)  
[Code and Syntax Highlighting](#code)  
[Tables](#tables)  
[Blockquotes](#blockquotes)  
[Inline HTML](#html)  
[Horizontal Rule](#hr)  
[Line Breaks](#lines)  
[YouTube Videos](#videos)  

<a name="headers"/>

## Headers

```no-highlight
# H1
## H2
### H3
#### H4
##### H5
###### H6

Alternatively, for H1 and H2, an underline-ish style:

Alt-H1
======

Alt-H2
------
```

# H1
## H2
### H3
#### H4
##### H5
###### H6

Alternatively, for H1 and H2, an underline-ish style:

Alt-H1
======

Alt-H2
------

<a name="emphasis"/>

## Emphasis

```no-highlight
Emphasis, aka italics, with *asterisks* or _underscores_.

Strong emphasis, aka bold, with **asterisks** or __underscores__.

Combined emphasis with **asterisks and _underscores_**.

Strikethrough uses two tildes. ~~Scratch this.~~
```

Emphasis, aka italics, with *asterisks* or _underscores_.

Strong emphasis, aka bold, with **asterisks** or __underscores__.

Combined emphasis with **asterisks and _underscores_**.

Strikethrough uses two tildes. ~~Scratch this.~~


<a name="lists"/>

## Lists

(In this example, leading and trailing spaces are shown with with dots: ⋅)

```no-highlight
1. First ordered list item
2. Another item
⋅⋅* Unordered sub-list. 
1. Actual numbers don't matter, just that it's a number
⋅⋅1. Ordered sub-list
4. And another item.

⋅⋅⋅You can have properly indented paragraphs within list items. Notice the blank line above, and the leading spaces (at least one, but we'll use three here to also align the raw Markdown).

⋅⋅⋅To have a line break without a paragraph, you will need to use two trailing spaces.⋅⋅
⋅⋅⋅Note that this line is separate, but within the same paragraph.⋅⋅
⋅⋅⋅(This is contrary to the typical GFM line break behaviour, where trailing spaces are not required.)

* Unordered list can use asterisks
- Or minuses
+ Or pluses
```

1. First ordered list item
2. Another item
  * Unordered sub-list. 
1. Actual numbers don't matter, just that it's a number
  1. Ordered sub-list
4. And another item.

   You can have properly indented paragraphs within list items. Notice the blank line above, and the leading spaces (at least one, but we'll use three here to also align the raw Markdown).

   To have a line break without a paragraph, you will need to use two trailing spaces.  
   Note that this line is separate, but within the same paragraph.  
   (This is contrary to the typical GFM line break behaviour, where trailing spaces are not required.)

* Unordered list can use asterisks
- Or minuses
+ Or pluses

<a name="links"/>

## Links

There are two ways to create links.

```no-highlight
[I'm an inline-style link](https://www.google.com)

[I'm an inline-style link with title](https://www.google.com "Google's Homepage")

[I'm a reference-style link][Arbitrary case-insensitive reference text]

[I'm a relative reference to a repository file](../blob/master/LICENSE)

[You can use numbers for reference-style link definitions][1]

Or leave it empty and use the [link text itself].

URLs and URLs in angle brackets will automatically get turned into links. 
http://www.example.com or <http://www.example.com> and sometimes 
example.com (but not on Github, for example).

Some text to show that the reference links can follow later.

[arbitrary case-insensitive reference text]: https://www.mozilla.org
[1]: http://slashdot.org
[link text itself]: http://www.reddit.com
```

[I'm an inline-style link](https://www.google.com)

[I'm an inline-style link with title](https://www.google.com "Google's Homepage")

[I'm a reference-style link][Arbitrary case-insensitive reference text]

[I'm a relative reference to a repository file](../blob/master/LICENSE)

[You can use numbers for reference-style link definitions][1]

Or leave it empty and use the [link text itself].

URLs and URLs in angle brackets will automatically get turned into links. 
http://www.example.com or <http://www.example.com> and sometimes 
example.com (but not on Github, for example).

Some text to show that the reference links can follow later.

[arbitrary case-insensitive reference text]: https://www.mozilla.org
[1]: http://slashdot.org
[link text itself]: http://www.reddit.com

<a name="images"/>

## Images

```no-highlight
Here's our logo (hover to see the title text):

Inline-style: 
![alt text](https://github.com/adam-p/markdown-here/raw/master/src/common/images/icon48.png "Logo Title Text 1")

Reference-style: 
![alt text][logo]

[logo]: https://github.com/adam-p/markdown-here/raw/master/src/common/images/icon48.png "Logo Title Text 2"
```

Here's our logo (hover to see the title text):

Inline-style: 
![alt text](https://github.com/adam-p/markdown-here/raw/master/src/common/images/icon48.png "Logo Title Text 1")

Reference-style: 
![alt text][logo]

[logo]: https://github.com/adam-p/markdown-here/raw/master/src/common/images/icon48.png "Logo Title Text 2"

<a name="code"/>

## Code and Syntax Highlighting

Code blocks are part of the Markdown spec, but syntax highlighting isn't. However, many renderers -- like Github's and *Markdown Here* -- support syntax highlighting. Which languages are supported and how those language names should be written will vary from renderer to renderer. *Markdown Here* supports highlighting for dozens of languages (and not-really-languages, like diffs and HTTP headers); to see the complete list, and how to write the language names, see the [highlight.js demo page](http://softwaremaniacs.org/media/soft/highlight/test.html).

```no-highlight
Inline `code` has `back-ticks around` it.
```

Inline `code` has `back-ticks around` it.

Blocks of code are either fenced by lines with three back-ticks <code>```</code>, or are indented with four spaces. I recommend only using the fenced code blocks -- they're easier and only they support syntax highlighting.

<pre lang="no-highlight"><code>```javascript
var s = "JavaScript syntax highlighting";
alert(s);
```
 
```python
s = "Python syntax highlighting"
print s
```
 
```
No language indicated, so no syntax highlighting. 
But let's throw in a &lt;b&gt;tag&lt;/b&gt;.
```
</code></pre>



```javascript
var s = "JavaScript syntax highlighting";
alert(s);
```

```python
s = "Python syntax highlighting"
print s
```

```
No language indicated, so no syntax highlighting in Markdown Here (varies on Github). 
But let's throw in a <b>tag</b>.
```


<a name="tables"/>

## Tables

Tables aren't part of the core Markdown spec, but they are part of GFM and *Markdown Here* supports them. They are an easy way of adding tables to your email -- a task that would otherwise require copy-pasting from another application.

```no-highlight
Colons can be used to align columns.

| Tables        | Are           | Cool  |
| ------------- |:-------------:| -----:|
| col 3 is      | right-aligned | $1600 |
| col 2 is      | centered      |   $12 |
| zebra stripes | are neat      |    $1 |

There must be at least 3 dashes separating each header cell.
The outer pipes (|) are optional, and you don't need to make the 
raw Markdown line up prettily. You can also use inline Markdown.

Markdown | Less | Pretty
--- | --- | ---
*Still* | `renders` | **nicely**
1 | 2 | 3
```

Colons can be used to align columns.

| Tables        | Are           | Cool |
| ------------- |:-------------:| -----:|
| col 3 is      | right-aligned | $1600 |
| col 2 is      | centered      |   $12 |
| zebra stripes | are neat      |    $1 |

There must be at least 3 dashes separating each header cell. The outer pipes (|) are optional, and you don't need to make the raw Markdown line up prettily. You can also use inline Markdown.

Markdown | Less | Pretty
--- | --- | ---
*Still* | `renders` | **nicely**
1 | 2 | 3

<a name="blockquotes"/>

## Blockquotes

```no-highlight
> Blockquotes are very handy in email to emulate reply text.
> This line is part of the same quote.

Quote break.

> This is a very long line that will still be quoted properly when it wraps. Oh boy let's keep writing to make sure this is long enough to actually wrap for everyone. Oh, you can *put* **Markdown** into a blockquote. 
```

> Blockquotes are very handy in email to emulate reply text.
> This line is part of the same quote.

Quote break.

> This is a very long line that will still be quoted properly when it wraps. Oh boy let's keep writing to make sure this is long enough to actually wrap for everyone. Oh, you can *put* **Markdown** into a blockquote. 

<a name="html"/>

## Inline HTML

You can also use raw HTML in your Markdown, and it'll mostly work pretty well. 

```no-highlight
<dl>
  <dt>Definition list</dt>
  <dd>Is something people use sometimes.</dd>

  <dt>Markdown in HTML</dt>
  <dd>Does *not* work **very** well. Use HTML <em>tags</em>.</dd>
</dl>
```

<dl>
  <dt>Definition list</dt>
  <dd>Is something people use sometimes.</dd>

  <dt>Markdown in HTML</dt>
  <dd>Does *not* work **very** well. Use HTML <em>tags</em>.</dd>
</dl>

<a name="hr"/>

## Horizontal Rule

```
Three or more...

---

Hyphens

***

Asterisks

___

Underscores
```

Three or more...

---

Hyphens

***

Asterisks

___

Underscores

<a name="lines"/>

## Line Breaks

My basic recommendation for learning how line breaks work is to experiment and discover -- hit &lt;Enter&gt; once (i.e., insert one newline), then hit it twice (i.e., insert two newlines), see what happens. You'll soon learn to get what you want. "Markdown Toggle" is your friend. 

Here are some things to try out:

```
Here's a line for us to start with.

This line is separated from the one above by two newlines, so it will be a *separate paragraph*.

This line is also a separate paragraph, but...
This line is only separated by a single newline, so it's a separate line in the *same paragraph*.
```

Here's a line for us to start with.

This line is separated from the one above by two newlines, so it will be a *separate paragraph*.

This line is also begins a separate paragraph, but...  
This line is only separated by a single newline, so it's a separate line in the *same paragraph*.

(Technical note: *Markdown Here* uses GFM line breaks, so there's no need to use MD's two-space line breaks.)

<a name="videos"/>

## YouTube Videos

They can't be added directly but you can add an image with a link to the video like this:

```no-highlight
<a href="http://www.youtube.com/watch?feature=player_embedded&v=YOUTUBE_VIDEO_ID_HERE
" target="_blank"><img src="http://img.youtube.com/vi/YOUTUBE_VIDEO_ID_HERE/0.jpg" 
alt="IMAGE ALT TEXT HERE" width="240" height="180" border="10" /></a>
```

Or, in pure Markdown, but losing the image sizing and border:

```no-highlight
[![IMAGE ALT TEXT HERE](http://img.youtube.com/vi/YOUTUBE_VIDEO_ID_HERE/0.jpg)](http://www.youtube.com/watch?v=YOUTUBE_VIDEO_ID_HERE)
```

Referencing a bug by #bugID in your git commit links it to the slip. For example #1. 

---

License: [CC-BY](https://creativecommons.org/licenses/by/3.0/)""", {}))
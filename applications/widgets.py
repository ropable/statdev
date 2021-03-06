"""
HTML Widget classes
"""

from __future__ import unicode_literals
import copy

from django.forms.utils import flatatt, to_current_timezone
from django.utils.html import conditional_escape, format_html, html_safe
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy
from django.forms import Media, MediaDefiningClass, Widget, CheckboxInput
from django.utils.safestring import SafeText

from django.utils.encoding import (
      force_str, force_text, python_2_unicode_compatible,
)

__all__ = (
    'ClearableMultipleFileInput', 'FileInput', 'RendererMixin', 'ChoiceFieldRenderer' 
)

MEDIA_TYPES = ('css', 'js')

class InputMultiFile(Widget):
    """
    Base class for all <input> widgets (except type='checkbox' and
    type='radio', which are special).
    """
    input_type = None  # Subclasses must define this.

    def format_value(self, value):
        if self.is_localized:
            return formats.localize_input(value)
        return value

    def render(self, name, value, attrs=None):
        if value is None:
            value = ''
        final_attrs = self.build_attrs(attrs, type=self.input_type, name=name, )
        if value != '':
            # Only add the 'value' attribute if a value is non-empty.
            final_attrs['value'] = force_text(self.format_value(value))
        return format_html('<input{} />', flatatt(final_attrs))

class FileInput(InputMultiFile):
    input_type = 'file'
    needs_multipart_form = True

    def render(self, name, value, attrs=None):
        return super(FileInput, self).render(name, None, attrs=attrs)

    def value_from_datadict(self, data, files, name):
        "File widgets take data from FILES, not POST"
        return files.get(name)

    def value_omitted_from_data(self, data, files, name):
        return name not in files

class ClearableMultipleFileInput(FileInput):
    initial_text = ugettext_lazy('Currently testing')
    input_text = ugettext_lazy('Change')
    clear_checkbox_label = ugettext_lazy('Clear')

    template_with_initial = (
        '%(initial_text)s: <a href="%(initial_url)s">%(initial)s</a> '
        '%(clear_template)s<br />%(input_text)s: %(input)s'
    )

    template_with_clear = '%(clear)s <label for="%(clear_checkbox_id)s">%(clear_checkbox_label)s</label>'

    def clear_checkbox_name(self, name):
        """
        Given the name of the file input, return the name of the clear checkbox
        input.
        """
        return name + '-clear'

    def clear_checkbox_id(self, name):
        """
        Given the name of the clear checkbox input, return the HTML id for it.
        """
        return name + '_id'

    def is_initial(self, value):
        """
        Return whether value is considered to be initial value.
        """
        return bool(value and getattr(value, 'url', False))

    def get_template_substitution_values(self, value):
        """
        Return value-related substitutions.
        """
        #return {
        #    'initial': conditional_escape(value),
        #    'initial_url': conditional_escape(value.url),
        #}

    def render(self, name, value, attrs=None):
        substitutions = {
            'initial_text': self.initial_text,
            'input_text': self.input_text,
            'clear_template': '',
            'clear_checkbox_label': self.clear_checkbox_label,
        }

        template = '%(input)s %(clearfiles)s'
        substitutions['input'] = super(ClearableMultipleFileInput, self).render(name, value, attrs)
        substitutions['clearfiles'] = ''
        if type(value) is list:
           substitutions['clearfiles'] = "<div class='col-sm-12'><Label>Files:</Label></div>"
           if value:
              for fi in value:
                  if fi:
                      substitutions['clearfiles'] += "<div class='col-sm-8'><A HREF='/media/"+fi['path']+"'>"+SafeText(fi['path'])[19:]+"</A>"+"</div>"
                      substitutions['clearfiles'] += "<div class='col-sm-4'><input type='checkbox' "
                      substitutions['clearfiles'] += " name='"+name+"-clear_multifileid-"+str(fi['fileid'])+"'"
                      substitutions['clearfiles'] += " id='"+name+"-clear_multifileid-"+str(fi['fileid'])+"'"
                      substitutions['clearfiles'] += " > Clear</div>"

        if self.is_initial(value):
            template = self.template_with_initial
            substitutions.update(self.get_template_substitution_values(value))
            if not self.is_required:
                checkbox_name = self.clear_checkbox_name(name)
                checkbox_id = self.clear_checkbox_id(checkbox_name)
                substitutions['clear_checkbox_name'] = conditional_escape(checkbox_name)
                substitutions['clear_checkbox_id'] = conditional_escape(checkbox_id)
                substitutions['clear'] = CheckboxInput().render(checkbox_name, False, attrs={'id': checkbox_id})
                substitutions['clear_template'] = self.template_with_clear % substitutions

        return mark_safe(template % substitutions)

    def value_from_datadict(self, data, files, name):
        upload = super(ClearableMultipleFileInput, self).value_from_datadict(data, files, name)
        if not self.is_required and CheckboxInput().value_from_datadict(
                data, files, self.clear_checkbox_name(name)):

            if upload:
                # If the user contradicts themselves (uploads a new file AND
                # checks the "clear" checkbox), we return a unique marker
                # object that FileField will turn into a ValidationError.
                return FILE_INPUT_CONTRADICTION
            # False signals to clear any existing value, as opposed to just None
            return False
        return upload

    def use_required_attribute(self, initial):
        return super(ClearableMultipleFileInput, self).use_required_attribute(initial) and not initial

    def value_omitted_from_data(self, data, files, name):
        return (
            super(ClearableMultipleFileInput, self).value_omitted_from_data(data, files, name) and
            self.clear_checkbox_name(name) not in data
        )

class RendererMixin(object):
    renderer = None  # subclasses must define this
    _empty_value = None

    def __init__(self, *args, **kwargs):
        # Override the default renderer if we were passed one.
        renderer = kwargs.pop('renderer', None)
        if renderer:
            self.renderer = renderer
        super(RendererMixin, self).__init__(*args, **kwargs)

    def subwidgets(self, name, value, attrs=None):
        for widget in self.get_renderer(name, value, attrs):
            yield widget

    def get_renderer(self, name, value, attrs=None):
        """Returns an instance of the renderer."""
        if value is None:
            value = self._empty_value
        final_attrs = self.build_attrs(attrs)
        return self.renderer(name, value, final_attrs, self.choices, self.caption)

    def render(self, name, value, attrs=None):
        return self.get_renderer(name, value, attrs).render()

    def id_for_label(self, id_):
        # Widgets using this RendererMixin are made of a collection of
        # subwidgets, each with their own <label>, and distinct ID.
        # The IDs are made distinct by a "_X" suffix, where X is the zero-based
        # index of the choice field. Thus, the label for the main widget should
        # reference the first subwidget, hence the "_0" suffix.
        if id_:
            id_ += '_0'
        return id_

class Select(Widget):
    allow_multiple_selected = False

    def __init__(self, attrs=None, choices=(), caption=None):
        super(Select, self).__init__(attrs)
        # choices can be any iterable, but we may need to render this widget
        # multiple times. Thus, collapse it into a list so it can be consumed
        # more than once.
        self.choices = list(choices)
        self.caption = caption

    def __deepcopy__(self, memo):
        obj = copy.copy(self)
        obj.attrs = self.attrs.copy()
        obj.choices = copy.copy(self.choices)
        memo[id(self)] = obj
        return obj

    def render(self, name, value, attrs=None):
        if value is None:
            value = ''
        final_attrs = self.build_attrs(attrs, name=name)
        output = [format_html('<select{}>', flatatt(final_attrs))]
        options = self.render_options([value])
        if options:
            output.append(options)
        output.append('</select>')
        return mark_safe('\n'.join(output))

    def render_option(self, selected_choices, option_value, option_label):
        if option_value is None:
            option_value = ''
        option_value = force_text(option_value)
        if option_value in selected_choices:
            selected_html = mark_safe(' selected="selected"')
            if not self.allow_multiple_selected:
                # Only allow for a single selection.
                selected_choices.remove(option_value)
        else:
            selected_html = ''
        return format_html('<option value="{}"{}>{}</option>', option_value, selected_html, force_text(option_label))

    def render_options(self, selected_choices):
        # Normalize to strings.
        selected_choices = set(force_text(v) for v in selected_choices)
        output = []
        for option_value, option_label in self.choices:
            if isinstance(option_label, (list, tuple)):
                output.append(format_html('<optgroup label="{}">', force_text(option_value)))
                for option in option_label:
                    output.append(self.render_option(selected_choices, *option))
                output.append('</optgroup>')
            else:
                output.append(self.render_option(selected_choices, option_value, option_label))
        return '\n'.join(output)

@html_safe
@python_2_unicode_compatible
class ChoiceFieldRenderer(object):
    """
    An object used by RadioSelect to enable customization of radio widgets.
    """

    choice_input_class = None
    outer_html = '<div{id_attr}>{content}</div>'
    inner_html = '<div class="radio">{choice_value}{sub_widgets}</div>'

    def __init__(self, name, value, attrs, choices, caption):
        self.name = name
        self.value = value
        self.attrs = attrs
        self.choices = choices
        self.caption = caption
    def __getitem__(self, idx):
        return list(self)[idx]

    def __iter__(self):
        for idx, choice in enumerate(self.choices):
            yield self.choice_input_class(self.name, self.value, self.attrs.copy(), choice, idx,self.caption)

    def __str__(self):
        return self.render()

    def render(self):
        """
        Outputs a <ul> for this set of choice fields.
        If an id was given to the field, it is applied to the <ul> (each
        item in the list will get an id of `$id_$i`).
        """
        id_ = self.attrs.get('id')
        output = []
        for i, choice in enumerate(self.choices):
            choice_value, choice_label = choice
            if isinstance(choice_label, (tuple, list)):
                attrs_plus = self.attrs.copy()
                if id_:
                    attrs_plus['id'] += '_{}'.format(i)
                sub_ul_renderer = self.__class__(
                    name=self.name,
                    value=self.value,
                    attrs=attrs_plus,
                    choices=choice_label,
                )
                sub_ul_renderer.choice_input_class = self.choice_input_class
                output.append(format_html(
                    self.inner_html, choice_value=choice_value,
                    sub_widgets=sub_ul_renderer.render(),
                ))
            else:
                w = self.choice_input_class(self.name, self.value, self.attrs.copy(), choice, i, self.caption)
                output.append(format_html(self.inner_html, choice_value=force_text(w), sub_widgets=''))
        return format_html(
            self.outer_html,
            id_attr=format_html(' id="{}"', id_) if id_ else '',
            content=mark_safe('\n'.join(output)),
        )

class SubWidget(object):
    """
    Some widgets are made of multiple HTML elements -- namely, RadioSelect.
    This is a class that represents the "inner" HTML element of a widget.
    """
    def __init__(self, parent_widget, name, value, attrs, choices, caption):
        self.parent_widget = parent_widget
        self.name, self.value = name, value
        self.attrs, self.choices = attrs, choices
        self.caption = caption
    def __str__(self):
        args = [self.name, self.value, self.attrs, self.caption]
        if self.choices:
            args.append(self.choices)
        return self.parent_widget.render(*args)

@python_2_unicode_compatible
class ChoiceInput(SubWidget):
    """
    An object used by ChoiceFieldRenderer that represents a single
    <input type='$input_type'>.
    """
    input_type = None  # Subclasses must define this

    def __init__(self, name, value, attrs, choice, index, caption):
        self.name = name
        self.value = value
        self.attrs = attrs
        self.choice_value = force_text(choice[0])
        self.choice_label = force_text(choice[1])
        self.index = index
        self.caption = caption
        if 'id' in self.attrs:
            self.attrs['id'] += "_%d" % self.index

    def __str__(self):
        return self.render()

    def render(self, name=None, value=None, attrs=None, caption=None):
        if self.id_for_label:
            label_for = format_html(' for="{}"', self.id_for_label)
        else:
            label_for = ''
        attrs = dict(self.attrs, **attrs) if attrs else self.attrs
#        print self.choice_value 
        caption_value = '' 
        if 'caption-'+self.choice_value in self.caption:
            caption_value = self.caption['caption-'+self.choice_value]
        return mark_safe(format_html(
            '<label{}>{} {}</label>', label_for, self.tag(attrs), self.choice_label ) + '<div class="radio-caption">'+caption_value+'</div>')

    def is_checked(self):
        return self.value == self.choice_value

    def tag(self, attrs=None):
        attrs = attrs or self.attrs
        final_attrs = dict(attrs, type=self.input_type, name=self.name, value=self.choice_value)
        final_attrs['class'] = 'radio-inline'
        if self.is_checked():
            final_attrs['checked'] = 'checked'
        return format_html('<input{} />', flatatt(final_attrs), self.caption['caption-1'])

    @property
    def id_for_label(self):
        return self.attrs.get('id', '')

class RadioChoiceInput(ChoiceInput):
    input_type = 'radio'

    def __init__(self, *args, **kwargs):
        super(RadioChoiceInput, self).__init__(*args, **kwargs)
        self.value = force_text(self.value)

class RadioFieldRenderer(ChoiceFieldRenderer):
    choice_input_class = RadioChoiceInput

class RadioSelectWithCaptions(RendererMixin, Select):
    renderer = RadioFieldRenderer
    _empty_value = ''


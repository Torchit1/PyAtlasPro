import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (FilteredElementCollector, Transaction, IndependentTag,
                               Reference, TagMode, TagOrientation, View, ViewType, XYZ)
from pyrevit import revit, forms, script, EXEC_PARAMS
from collections import defaultdict
import config

doc = revit.doc
output = script.get_output()
element_cache = {}  # Global cache for elements

def is_element_visible_in_view(doc, view, element):
    category_id = element.Category.Id
    collector = FilteredElementCollector(doc, view.Id).OfCategoryId(category_id).WhereElementIsNotElementType()
    return any(e.Id == element.Id for e in collector)

def get_projected_center_point(element):
    bbox = element.get_BoundingBox(None)
    if not bbox:
        return None
    center = bbox.Min + 0.5 * (bbox.Max - bbox.Min)
    return center

def tag_elements_in_view(doc, view, elements, tagged_views_info, progress_bar):
    toggle_settings = config.load_toggle_settings()
    existing_tags = FilteredElementCollector(doc, view.Id).OfClass(IndependentTag)
    already_tagged_element_ids = set(tag.TaggedLocalElementId.IntegerValue for tag in existing_tags)

    for idx, element in enumerate(elements):
        progress_bar.update_progress(idx, len(elements))

        if toggle_settings['toggle_tagged'] and element.Id.IntegerValue in already_tagged_element_ids:
            continue

        if toggle_settings['toggle_visibility'] and not is_element_visible_in_view(doc, view, element):
            continue

        center_point = get_projected_center_point(element)
        if center_point is None:
            continue

        try:
            tag = None
            if element.Category.Name == "Windows" and view.ViewType == ViewType.FloorPlan:
                # Create a tag with a leader for windows
                tag = IndependentTag.Create(doc, view.Id, Reference(element), True, TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, center_point)
            else:
                # Create a tag without a leader for other elements
                tag = IndependentTag.Create(doc, view.Id, Reference(element), False, TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, center_point)

            # Check if the tag is blank (no text) and delete it
            if toggle_settings['check_blank_tag'] and tag and not tag.TagText.strip():
                doc.Delete(tag.Id)

        except Exception as e:
            print("Error creating tag: " + str(e))

def select_categories(doc):
    categories = doc.Settings.Categories
    specific_categories = config.load_configs()
    category_names = [cat.Name for cat in categories if cat.Name in specific_categories and cat.AllowsBoundParameters]
    selected_category_names = forms.SelectFromList.show(category_names, 
                                                        multiselect=True, 
                                                        title='Select Categories to Tag', 
                                                        button_name='Select')
    if selected_category_names is None:
        raise SystemExit
    return [categories.get_Item(name) for name in selected_category_names]

def select_elements(doc, selected_categories):
    selected_elements = []
    for category in selected_categories:
        if category.Id in element_cache:
            selected_elements.extend(element_cache[category.Id])
        else:
            elements_collector = FilteredElementCollector(doc).OfCategoryId(category.Id).WhereElementIsNotElementType()
            category_elements = [el for el in elements_collector]
            element_cache[category.Id] = category_elements
            selected_elements.extend(category_elements)
    return selected_elements

def select_views(doc):
    all_views = FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements()
    target_view_types = [ViewType.FloorPlan, ViewType.Elevation, ViewType.Section]
    available_views = [v for v in all_views if v.ViewType in target_view_types and not v.IsTemplate]
    view_names = sorted([v.Name for v in available_views])
    selected_view_names = forms.SelectFromList.show(view_names, 
                                                    multiselect=True, 
                                                    title='Select Views',
                                                    button_name='Select')
    if selected_view_names is None:
        raise SystemExit
    return [v for v in available_views if v.Name in selected_view_names]

def tag_elements_in_selected_views(doc, selected_views, selected_elements):
    tagged_views_info = defaultdict(list)
    with forms.ProgressBar(title='Tagging Elements...', maximum=len(selected_elements)) as pb:
        t = Transaction(doc, 'Tag Selected Elements in All Views')
        t.Start()
        try:
            for view in selected_views:
                tag_elements_in_view(doc, view, selected_elements, tagged_views_info, pb)
            t.Commit()
        except Exception:
            t.RollBack()
            raise

try:
    selected_categories = select_categories(doc)
    selected_elements = select_elements(doc, selected_categories)
    selected_views = select_views(doc)
    if selected_elements and selected_views:
        tag_elements_in_selected_views(doc, selected_views, selected_elements)
except SystemExit:
    pass  # Silently exit if user closes the dialog
except Exception as e:
    print("Error: " + str(e))
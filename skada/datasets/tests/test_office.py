import numpy as np

from skada.datasets import (
    Office31CategoriesPreset,
    Office31Domain,
    fetch_office31_decaf,
    fetch_office31_surf,
)

import pytest


_CALTECH256 = Office31CategoriesPreset.CALTECH256
_ALL = Office31CategoriesPreset.ALL


@pytest.mark.parametrize(
    "domain, X_shape, y_shape, categories, n_categories",
    [
        # load by name
        ("amazon", (2817, 1000), (2817,), None, 31),
        ("webcam",  (795, 1000), (795,),  None, 31),
        ("dslr",    (498, 1000), (498,), None, 31),
        # load by enum
        (Office31Domain.AMAZON, (2817, 1000), (2817,), None, 31),
        (Office31Domain.WEBCAM,  (795, 1000), (795,),  None, 31),
        (Office31Domain.DSLR,    (498, 1000), (498,),  None, 31),
        # caltech categories
        (Office31Domain.AMAZON, (958, 1000), (958,), _CALTECH256, 10),
        (Office31Domain.WEBCAM, (295, 1000), (295,), _CALTECH256, 10),
        (Office31Domain.DSLR,   (157, 1000), (157,), _CALTECH256, 10),
        # other categories
        (Office31Domain.AMAZON, (2817, 1000), (2817,), _ALL, 31),
        (Office31Domain.AMAZON, (82, 1000), (82,), ['bike'], 1),
    ]
)
def test_decaf_fetcher(tmp_folder, domain, X_shape, y_shape, categories, n_categories):
    X, y = fetch_office31_decaf(
        domain,
        data_home=tmp_folder,
        categories=categories,
        return_X_y=True,
    )
    assert X.shape == X_shape
    assert y.shape == y_shape
    assert np.unique(y).shape[0] == n_categories


@pytest.mark.parametrize(
    "domain, X_shape, y_shape, categories, n_categories",
    [
        # load by name
        ("amazon", (2813, 800), (2813,), None, 31),
        ("webcam",  (795, 800), (795,),  None, 31),
        ("dslr",    (498, 800), (498,), None, 31),
        # load by enum
        (Office31Domain.AMAZON, (2813, 800), (2813,), None, 31),
        (Office31Domain.WEBCAM,  (795, 800), (795,),  None, 31),
        (Office31Domain.DSLR,    (498, 800), (498,),  None, 31),
        # caltech categories
        (Office31Domain.AMAZON, (958, 800), (958,), _CALTECH256, 10),
        (Office31Domain.WEBCAM, (295, 800), (295,), _CALTECH256, 10),
        (Office31Domain.DSLR,   (157, 800), (157,), _CALTECH256, 10),
        # other categories
        (Office31Domain.AMAZON, (2813, 800), (2813,), _ALL, 31),
        (Office31Domain.AMAZON, (82, 800), (82,), ['bike'], 1),
    ]
)
def test_surf_fetcher(tmp_folder, domain, X_shape, y_shape, categories, n_categories):
    X, y = fetch_office31_surf(
        domain,
        data_home=tmp_folder,
        categories=categories,
        return_X_y=True,
    )
    assert X.shape == X_shape
    assert y.shape == y_shape
    assert np.unique(y).shape[0] == n_categories


def test_categories_mapping(tmp_folder):
    categories = ['bike', 'mouse']
    data = fetch_office31_surf(
        Office31Domain.AMAZON,
        data_home=tmp_folder,
        categories=categories,
    )
    assert data.target_names == categories


def test_unknown_domain_failure(tmp_folder):
    with pytest.raises(ValueError):
        fetch_office31_surf("unknown-domain", data_home=tmp_folder)


def test_unknown_category_warning(tmp_folder):
    with pytest.warns():
        fetch_office31_surf(
            Office31Domain.AMAZON,
            data_home=tmp_folder,
            categories=['bike', 'mug', 'this-wont-be-found'],
        )

# Author: Theo Gnassounou <theo.gnassounou@inria.fr>
#         Remi Flamary <remi.flamary@polytechnique.edu>
#         Alexandre Gramfort <alexandre.gramfort@inria.fr>
#
# License: BSD 3-Clause

from abc import abstractmethod
from skorch import NeuralNetClassifier
from skorch.dataset import unpack_data
from skorch.dataset import get_len
from skorch.utils import TeeGenerator

import numpy as np

from .utils import _register_forwards_hook


class BaseDANetwork(NeuralNetClassifier):
    """Base class for all DA estimators.

    Based on skorch class and add X_target during the training.

    Parameters
    ----------
    module : torch module (class or instance)
        A PyTorch :class:`~torch.nn.Module`. In general, the
        uninstantiated class should be passed, although instantiated
        modules will also work.
    criterion : torch criterion (class)
        The uninitialized criterion (loss) used to optimize the
        module.
    layer_names : list of tuples
        The names of the module's layers whose outputs are
        collected during the training.
    **kwargs : dict
        Keyword arguments passed to the skorch Model class.

    Attributes
    ----------
    intermediate_layers : dict
        The dict where the outputs of layers are stored during the training.
    """
    def __init__(
        self,
        module,
        criterion,
        layer_names,
        **kwargs
    ):
        super().__init__(
            module,
            criterion=criterion,
            **kwargs
        )
        self.layer_names = layer_names
        self.intermediate_layers = {}

    @abstractmethod
    def _get_loss_da(self):
        """Compute the domain adaptation loss"""
        pass

    def train_step_single(self, batch, batch_target, **fit_params):
        """Compute y_pred, y_pred_target, loss value, and update net's
        gradients. The module is set to be in train mode (e.g. dropout is
        applied).

        Parameters
        ----------
        batch
            A single batch returned by the data loader.
        batch_target
            A single target batch returned by the target data loader.
        **fit_params : dict
            Additional parameters passed to the ``forward`` method of
            the module and to the ``self.train_split`` call.

        Returns
        -------
        step : dict
            A dictionary ``{'loss': loss, 'y_pred': y_pred,
            'y_pred_target': y_pred_target}``, where the
            float ``loss`` is the result of the loss function,
            ``y_pred`` the prediction generated by the PyTorch module
            and ``y_pred_target`` the prediction generated by
            the PyTorch module for target samples.
        """
        self._set_training(True)
        Xi, yi = unpack_data(batch)
        y_pred = self.infer(Xi, **fit_params)
        embedd = [
            self.intermediate_layers[layer_name] for layer_name in self.layer_names
        ]
        Xi_target, _ = unpack_data(batch_target)
        y_pred_target = self.infer(Xi_target, **fit_params)
        embedd_target = [
            self.intermediate_layers[layer_name] for layer_name in self.layer_names
        ]
        loss, loss_classif, loss_da = self._get_loss_da(
            y_pred,
            yi,
            embedd,
            embedd_target,
            X=Xi,
            y_pred_target=y_pred_target,
            training=True
        )

        loss.backward()
        return {
            'loss': loss,
            'loss_classif': loss_classif,
            'loss_da': loss_da,
            'y_pred': y_pred,
            'y_pred_target': y_pred_target
        }

    def train_step(self, batch, batch_target, **fit_params):
        """Prepares a loss function callable and pass it to the optimizer,
        hence performing one optimization step.

        Loss function callable as required by some optimizers (and accepted by
        all of them):
        https://pytorch.org/docs/master/optim.html#optimizer-step-closure
        The module is set to be in train mode (e.g. dropout is
        applied).

        Parameters
        ----------
        batch
            A single batch returned by the data loader.
        batch_target
            A single target batch returned by the target data loader.
        **fit_params : dict
            Additional parameters passed to the ``forward`` method of
            the module and to the train_split call.

        Returns
        -------
        step : dict
            A dictionary ``{'loss': loss, 'y_pred': y_pred,
            'y_pred_target': y_pred_target}``, where the
            float ``loss`` is the result of the loss function,
            ``y_pred`` the prediction generated by the PyTorch module
            and ``y_pred_target`` the prediction generated by
            the PyTorch module for target samples.
        """
        step_accumulator = self.get_train_step_accumulator()

        def step_fn():
            self._zero_grad_optimizer()
            step = self.train_step_single(batch, batch_target, **fit_params)
            step_accumulator.store_step(step)

            self.notify(
                'on_grad_computed',
                named_parameters=TeeGenerator(self.get_all_learnable_params()),
                batch=batch,
            )
            return step['loss']

        self._step_optimizer(step_fn)
        return step_accumulator.get_step()

    def fit_loop(self, X, y=None, X_target=None, epochs=None, **fit_params):
        """The proper fit loop.

        Contains the logic of what actually happens during the fit
        loop.

        Parameters
        ----------
        X : input data, compatible with skorch.dataset.Dataset
            By default, you should be able to pass:
                * numpy arrays
                * torch tensors
                * pandas DataFrame or Series
                * scipy sparse CSR matrices
                * a dictionary of the former three
                * a list/tuple of the former three
                * a Dataset
            If this doesn't work with your data, you have to pass a
            ``Dataset`` that can deal with the data.
        y : target data, compatible with skorch.dataset.Dataset
            The same data types as for ``X`` are supported. If your X is
            a Dataset that contains the target, ``y`` may be set to
            None.
        X_target : input target data, compatible with skorch.dataset.Dataset
            By default, you should be able to pass:
                * numpy arrays
                * torch tensors
                * pandas DataFrame or Series
                * scipy sparse CSR matrices
                * a dictionary of the former three
                * a list/tuple of the former three
                * a Dataset
            If this doesn't work with your data, you have to pass a
            ``Dataset`` that can deal with the data.
        epochs : int or None (default=None)
            If int, train for this number of epochs; if None, use
            ``self.max_epochs``.
        **fit_params : dict
            Additional parameters passed to the ``forward`` method of
            the module and to the ``self.train_split`` call.
        """
        self.check_data(X, y)
        epochs = epochs if epochs is not None else self.max_epochs

        dataset_train, dataset_valid = self.get_split_datasets(
            X, y, **fit_params)
        dataset_target = self.get_dataset(X_target, np.zeros(len(X_target)))
        on_epoch_kwargs = {
            'dataset_train': dataset_train,
            'dataset_target': dataset_target,
            'dataset_valid': dataset_valid,
        }
        iterator_train = self.get_iterator(dataset_train, training=True)
        iterator_valid = None
        if dataset_valid is not None:
            iterator_valid = self.get_iterator(dataset_valid, training=False)
        iterator_target = self.get_iterator(dataset_target, training=True)

        for _ in range(epochs):
            self.notify('on_epoch_begin', **on_epoch_kwargs)

            self.run_single_epoch(
                            iterator_train,
                            iterator_target=iterator_target,
                            training=True,
                            prefix="train",
                            step_fn=self.train_step,
                            **fit_params
                        )

            self.run_single_epoch(iterator_valid, training=False, prefix="valid",
                                  step_fn=self.validation_step, **fit_params)

            self.notify("on_epoch_end", **on_epoch_kwargs)
        return self

    def run_single_epoch(
        self, iterator, training, prefix, step_fn, iterator_target=None, **fit_params
    ):
        """Compute a single epoch of train or validation.
        Parameters
        ----------
        iterator : torch DataLoader or None
            The initialized ``DataLoader`` to loop over. If None, skip this step.
        training : bool
            Whether to set the module to train mode or not.
        prefix : str
            Prefix to use when saving to the history.
        step_fn : callable
            Function to call for each batch.
        iterator_target : torch DataLoader or None
            The initialized target ``DataLoader`` to loop over.
        **fit_params : dict
            Additional parameters passed to the ``step_fn``.
        """
        if iterator is None:
            return

        if training:
            batch_count = 0
            for batch in iterator:
                batch_target = next(iter(iterator_target))
                if len(batch[0]) != len(batch_target[0]):
                    break
                self.notify("on_batch_begin", batch=batch, training=training)
                step = step_fn(batch, batch_target, **fit_params)
                self.history.record_batch(prefix + "_loss", step["loss"].item())
                self.history.record_batch(
                    prefix + "_loss_classif", step["loss_classif"].item()
                )
                self.history.record_batch(prefix + "_loss_da", step["loss_da"].item())
                batch_size = (get_len(batch[0]) if isinstance(batch, (tuple, list))
                              else get_len(batch))
                self.history.record_batch(prefix + "_batch_size", batch_size)
                self.notify("on_batch_end", batch=batch, training=training, **step)
                batch_count += 1
        else:
            batch_count = 0
            for batch in iterator:
                self.notify("on_batch_begin", batch=batch, training=training)
                step = step_fn(batch, **fit_params)
                self.history.record_batch(prefix + "_loss", step["loss"].item())
                batch_size = (get_len(batch[0]) if isinstance(batch, (tuple, list))
                              else get_len(batch))
                self.history.record_batch(prefix + "_batch_size", batch_size)
                self.notify("on_batch_end", batch=batch, training=training, **step)
                batch_count += 1

        self.history.record(prefix + "_batch_count", batch_count)

    # pylint: disable=unused-argument
    def partial_fit(self, X, y=None, X_target=None, classes=None, **fit_params):
        """Fit the module.

        If the module is initialized, it is not re-initialized, which
        means that this method should be used if you want to continue
        training a model (warm start).

        Parameters
        ----------
        X : input data, compatible with skorch.dataset.Dataset
            By default, you should be able to pass:
                * numpy arrays
                * torch tensors
                * pandas DataFrame or Series
                * scipy sparse CSR matrices
                * a dictionary of the former three
                * a list/tuple of the former three
                * a Dataset
            If this doesn't work with your data, you have to pass a
                ``Dataset`` that can deal with the data.
        y : target data, compatible with skorch.dataset.Dataset
            The same data types as for ``X`` are supported. If your X is
            a Dataset that contains the target, ``y`` may be set to
            None.
        X_target : input target data, compatible with skorch.dataset.Dataset
            By default, you should be able to pass:
                * numpy arrays
                * torch tensors
                * pandas DataFrame or Series
                * scipy sparse CSR matrices
                * a dictionary of the former three
                * a list/tuple of the former three
                * a Dataset
            If this doesn't work with your data, you have to pass a
            ``Dataset`` that can deal with the data.
        classes : array, sahpe (n_classes,)
            Solely for sklearn compatibility, currently unused.
        **fit_params : dict
            Additional parameters passed to the ``forward`` method of
            the module and to the ``self.train_split`` call.
        """
        if not self.initialized_:
            self.initialize()

        self.notify('on_train_begin', X=X, y=y)
        try:
            self.fit_loop(X, y, X_target, **fit_params)
        except KeyboardInterrupt:
            pass
        self.notify('on_train_end', X=X, y=y)
        return self

    def fit(self, X, y=None, X_target=None, **fit_params):
        """Initialize and fit the module.

        If the module was already initialized, by calling fit, the
        module will be re-initialized (unless ``warm_start`` is True).

        Parameters
        ----------
        X : input data, compatible with skorch.dataset.Dataset
            By default, you should be able to pass:
                * numpy arrays
                * torch tensors
                * pandas DataFrame or Series
                * scipy sparse CSR matrices
                * a dictionary of the former three
                * a list/tuple of the former three
                * a Dataset
            If this doesn't work with your data, you have to pass a
            ``Dataset`` that can deal with the data.
        y : target data, compatible with skorch.dataset.Dataset
            The same data types as for ``X`` are supported. If your X is
            a Dataset that contains the target, ``y`` may be set to
            None.
        X_target : input target data, compatible with skorch.dataset.Dataset
            By default, you should be able to pass:
                * numpy arrays
                * torch tensors
                * pandas DataFrame or Series
                * scipy sparse CSR matrices
                * a dictionary of the former three
                * a list/tuple of the former three
                * a Dataset
            If this doesn't work with your data, you have to pass a
            ``Dataset`` that can deal with the data.
        **fit_params : dict
            Additional parameters passed to the ``forward`` method of
            the module and to the ``self.train_split`` call.
        """
        if not self.warm_start or not self.initialized_:
            self.initialize()

        self.partial_fit(X, y, X_target, **fit_params)
        return self

    def initialize_module(self):
        """Initializes the module and add hooks to return features.

        If the module is already initialized and no parameter was changed, it
        will be left as is.
        """
        kwargs = self.get_params_for('module')
        module = self.initialized_instance(self.module, kwargs)
        # pylint: disable=attribute-defined-outside-init
        self.module_ = module
        _register_forwards_hook(
            self.module_, self.intermediate_layers, self.layer_names
        )
        return self
from math import pi
from typing import Any, Optional

import torch
from torch import Tensor

from ..constants import G_over_c2, arcsec_to_rad, rad_to_arcsec
from ..cosmology import Cosmology
from ..utils import translate_rotate
from .base import ThinLens

DELTA = 200.0

__all__ = ("NFW",)


class NFW(ThinLens):
    """
    NFW lens class. This class models a lens using the Navarro-Frenk-White (NFW) profile.
    The NFW profile is a spatial density profile of dark matter halo that arises in 
    cosmological simulations.

    Attributes:
        z_l (Optional[Tensor]): Redshift of the lens. Default is None.
        x0 (Optional[Tensor]): x-coordinate of the lens center in the lens plane. 
            Default is None.
        y0 (Optional[Tensor]): y-coordinate of the lens center in the lens plane. 
            Default is None.
        m (Optional[Tensor]): Mass of the lens. Default is None.
        c (Optional[Tensor]): Concentration parameter of the lens. Default is None.
        s (float): Softening parameter to avoid singularities at the center of the lens. 
            Default is 0.0.

    Methods:
        get_scale_radius: Returns the scale radius of the lens.
        get_scale_density: Returns the scale density of the lens.
        get_convergence_s: Returns the dimensionless surface mass density of the lens.
        _f: Helper method for computing deflection angles.
        _g: Helper method for computing lensing potential.
        _h: Helper method for computing reduced deflection angles.
        deflection_angle_hat: Computes the reduced deflection angle.
        deflection_angle: Computes the deflection angle.
        convergence: Computes the convergence (dimensionless surface mass density).
        potential: Computes the lensing potential.
    """
    def __init__(
        self,
        name: str,
        cosmology: Cosmology,
        z_l: Optional[Tensor] = None,
        x0: Optional[Tensor] = None,
        y0: Optional[Tensor] = None,
        m: Optional[Tensor] = None,
        c: Optional[Tensor] = None,
        s: float = 0.0,
    ):
        """
        Initialize an instance of the NFW lens class.

        Args:
            name (str): Name of the lens instance.
            cosmology (Cosmology): An instance of the Cosmology class which contains 
                information about the cosmological model and parameters.
            z_l (Optional[Tensor]): Redshift of the lens. Default is None.
            x0 (Optional[Tensor]): x-coordinate of the lens center in the lens plane. 
                Default is None.
            y0 (Optional[Tensor]): y-coordinate of the lens center in the lens plane. 
                Default is None.
            m (Optional[Tensor]): Mass of the lens. Default is None.
            c (Optional[Tensor]): Concentration parameter of the lens. Default is None.
            s (float): Softening parameter to avoid singularities at the center of the lens. 
                Default is 0.0.
        """
        super().__init__(name, cosmology, z_l)

        self.add_param("x0", x0)
        self.add_param("y0", y0)
        self.add_param("m", m)
        self.add_param("c", c)
        self.s = s

    def get_scale_radius(self, z_l, m, c, P: "Packed") -> Tensor:
        """
        Calculate the scale radius of the lens.

        Args:
            z_l (Tensor): Redshift of the lens.
            m (Tensor): Mass of the lens.
            c (Tensor): Concentration parameter of the lens.
            x (dict): Additional parameters.

        Returns:
            Tensor: The scale radius of the lens in Mpc.
        """
        critical_density = self.cosmology.critical_density(z_l, P)
        r_delta = (3 * m / (4 * pi * DELTA * critical_density)) ** (1 / 3)
        return 1 / c * r_delta

    def get_scale_density(self, z_l, c, P: "Packed") -> Tensor:
        """
        Calculate the scale density of the lens.

        Args:
            z_l (Tensor): Redshift of the lens.
            c (Tensor): Concentration parameter of the lens.
            P (dict): Additional parameters.

        Returns:
            Tensor: The scale density of the lens in solar masses per Mpc cubed.
        """
        return (
            DELTA
            / 3
            * self.cosmology.critical_density(z_l, P)
            * c**3
            / ((1 + c).log() - c / (1 + c))
        )

    def get_convergence_s(self, z_l, z_s, m, c, P) -> Tensor:
        """
        Calculate the dimensionless surface mass density of the lens.

        Args:
            z_l (Tensor): Redshift of the lens.
            z_s (Tensor): Redshift of the source.
            m (Tensor): Mass of the lens.
            c (Tensor): Concentration parameter of the lens.
            P (dict): Additional parameters.

        Returns:
            Tensor: The dimensionless surface mass density of the lens.
        """
        critical_surface_density = self.cosmology.critical_surface_density(z_l, z_s, P)
        return self.get_scale_density(z_l, c, P) * self.get_scale_radius(z_l, m, c, P) / critical_surface_density

    @staticmethod
    def _f(x: Tensor) -> Tensor:
        """
        Helper method for computing deflection angles.

        Args:
            x (Tensor): The scaled radius (xi / xi_0).

        Returns:
            Tensor: Result of the deflection angle computation.
        """
        # TODO: generalize beyond torch, or patch Tensor
        return torch.where(
            x > 1,
            1 - 2 / (x**2 - 1).sqrt() * ((x - 1) / (x + 1)).sqrt().arctan(),
            torch.where(
                x < 1,
                1 - 2 / (1 - x**2).sqrt() * ((1 - x) / (1 + x)).sqrt().arctanh(),
                0.0,
            ),
        )

    @staticmethod
    def _g(x: Tensor) -> Tensor:
        """
        Helper method for computing lensing potential.

        Args:
            x (Tensor): The scaled radius (xi / xi_0).

        Returns:
            Tensor: Result of the lensing potential computation.
        """
        # TODO: generalize beyond torch, or patch Tensor
        term_1 = (x / 2).log() ** 2
        term_2 = torch.where(
            x > 1,
            (1 / x).arccos() ** 2,
            torch.where(x < 1, -(1 / x).arccosh() ** 2, 0.0),
        )
        return term_1 + term_2

    @staticmethod
    def _h(x: Tensor) -> Tensor:
        """
        Helper method for computing reduced deflection angles.

        Args:
            x (Tensor): The scaled radius (xi / xi_0).

        Returns:
            Tensor: Result of the reduced deflection angle computation.
        """
        term_1 = (x / 2).log()
        term_2 = torch.where(
            x > 1,
            term_1 + (1 / x).arccos() * 1 / (x**2 - 1).sqrt(),
            torch.where(
                x < 1,
                term_1 + (1 / x).arccosh() * 1 / (1 - x**2).sqrt(),
                1.0 + torch.tensor(1 / 2).log(),
            ),
        )
        return term_2

    def deflection_angle_hat(
        self, x: Tensor, y: Tensor, z_s: Tensor, P: "Packed" = None
    ) -> tuple[Tensor, Tensor]:
        """
        Compute the reduced deflection angle.

        Args:
            x (Tensor): x-coordinates in the lens plane.
            y (Tensor): y-coordinates in the lens plane.
            z_s (Tensor): Redshifts of the sources.
            P ("Packed"): Additional parameters.

        Returns:
            tuple[Tensor, Tensor]: The reduced deflection angles in the x and y directions.
        """
        z_l, x0, y0, m, c = self.unpack(P)

        x, y = translate_rotate(x, y, x0, y0)
        th = (x**2 + y**2).sqrt() + self.s
        d_l = self.cosmology.angular_diameter_distance(z_l, P)
        scale_radius = self.get_scale_radius(z_l, m, c, P)
        xi = d_l * th * arcsec_to_rad
        r = xi / scale_radius

        deflection_angle = (
            16
            * pi
            * G_over_c2
            * self.get_scale_density(z_l, c, P)
            * scale_radius**3
            * self._h(r)
            * rad_to_arcsec
            / xi
        )

        ax = deflection_angle * x / th
        ay = deflection_angle * y / th
        return ax, ay

    def deflection_angle(
        self, x: Tensor, y: Tensor, z_s: Tensor, P: "Packed" = None
    ) -> tuple[Tensor, Tensor]:
        """
        Compute the deflection angle.

        Args:
            x (Tensor): x-coordinates in the lens plane.
            y (Tensor): y-coordinates in the lens plane.
            z_s (Tensor): Redshifts of the sources.
            P ("Packed"): Additional parameters.

        Returns:
            tuple[Tensor, Tensor]: The deflection angles in the x and y directions.
        """
        z_l = self.unpack(P)[0]

        d_s = self.cosmology.angular_diameter_distance(z_s, P)
        d_ls = self.cosmology.angular_diameter_distance_z1z2(z_l, z_s, P)
        ahx, ahy = self.deflection_angle_hat(x, y, z_s, P)
        return d_ls / d_s * ahx, d_ls / d_s * ahy

    def convergence(
        self, x: Tensor, y: Tensor, z_s: Tensor, P: "Packed" = None
    ) -> Tensor:
        """
        Compute the convergence (dimensionless surface mass density).

        Args:
            x (Tensor): x-coordinates in the lens plane.
            y (Tensor): y-coordinates in the lens plane.
            z_s (Tensor): Redshifts of the sources.
            P ("Packed"): Additional parameters.

        Returns:
            Tensor: The convergence (dimensionless surface mass density).
        """
        z_l, x0, y0, m, c = self.unpack(P)

        x, y = translate_rotate(x, y, x0, y0)
        th = (x**2 + y**2).sqrt() + self.s
        d_l = self.cosmology.angular_diameter_distance(z_l, P)
        scale_radius = self.get_scale_radius(z_l, m, c, P)
        xi = d_l * th * arcsec_to_rad
        r = xi / scale_radius  # xi / xi_0
        convergence_s = self.get_convergence_s(z_l, z_s, m, c, P)
        return 2 * convergence_s * self._f(r) / (r**2 - 1)

    def potential(
        self, x: Tensor, y: Tensor, z_s: Tensor, P: "Packed" = None
    ) -> Tensor:
        """
        Compute the lensing potential.

        Args:
            x (Tensor): x-coordinates in the lens plane.
            y (Tensor): y-coordinates in the lens plane.
            z_s (Tensor): Redshifts of the sources.
            P ("Packed"): Additional parameters.

        Returns:
            Tensor: The lensing potential.
        """
        z_l, x0, y0, m, c = self.unpack(P)

        x, y = translate_rotate(x, y, x0, y0)
        th = (x**2 + y**2).sqrt() + self.s
        d_l = self.cosmology.angular_diameter_distance(z_l, P)
        scale_radius = self.get_scale_radius(z_l, m, c, P)
        xi = d_l * th * arcsec_to_rad
        r = xi / scale_radius  # xi / xi_0
        convergence_s = self.get_convergence_s(z_l, z_s, m, c, P)
        return 2 * convergence_s * self._g(r) * scale_radius**2 / (d_l**2 * arcsec_to_rad**2)

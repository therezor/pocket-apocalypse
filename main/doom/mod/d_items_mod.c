/* Emacs style mode select   -*- C++ -*-
 *-----------------------------------------------------------------------------
 *
 *
 *  PrBoom: a Doom port merged with LxDoom and LSDLDoom
 *  based on BOOM, a modified and improved DOOM engine
 *  Copyright (C) 1999 by
 *  id Software, Chi Hoang, Lee Killough, Jim Flynn, Rand Phares, Ty Halderman
 *  Copyright (C) 1999-2000 by
 *  Jess Haas, Nicolas Kalkhof, Colin Phipps, Florian Schulze
 *  Copyright 2005, 2006 by
 *  Florian Schulze, Colin Phipps, Neil Stevens, Andrey Budko
 *
 *  This program is free software; you can redistribute it and/or
 *  modify it under the terms of the GNU General Public License
 *  as published by the Free Software Foundation; either version 2
 *  of the License, or (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
 *  02111-1307, USA.
 *
 * DESCRIPTION:
 *  Something to do with weapon sprite frames. Don't ask me.
 *
 *-----------------------------------------------------------------------------
 */

// We are referring to sprite numbers.
#include "doomtype.h"
#include "info.h"

#include "d_items.h"


//
// PSPRITE ACTIONS for waepons.
// This struct controls the weapon animations.
//
// Each entry is:
//  ammo/amunition type
//  upstate
//  downstate
//  readystate
//  atkstate, i.e. attack/fire/hit frame
//  flashstate, muzzle flash
//
const weaponinfo_t weaponinfo[NUMWEAPONS] =
{
    {
        // fist
        am_noammo,
        S_MODSPARE1,
        S_MODSPARE3,
        S_MODSPARE0,
        S_MODSPARE6,
        S_LIGHTDONE
    },
    {
        // pistol
        am_clip,
        S_MODSPARE28,
        S_MODSPARE30,
        S_MODSPARE27,
        S_MODSPARE33,
        S_LIGHTDONE
    },
    {
        // shotgun
        am_shell,
        S_MODSPARE79,
        S_MODSPARE81,
        S_MODSPARE78,
        S_MODSPARE84,
        S_LIGHTDONE
    },
    {
        // chaingun
        am_clip,
        S_MODSPARE145,
        S_MODSPARE147,
        S_MODSPARE144,
        S_MODSPARE149,
        S_LIGHTDONE
    },
    {
        // missile launcher
        am_misl,
        S_MODSPARE191,
        S_MODSPARE193,
        S_MODSPARE190,
        S_MODSPARE196,
        S_LIGHTDONE
    },
    {
        // plasma rifle
        am_cell,
        S_MODSPARE558,
        S_MODSPARE560,
        S_MODSPARE557,
        S_MODSPARE562,
        S_LIGHTDONE
    },
    {
        // bfg 9000
        am_cell,
        S_BFGUP,
        S_BFGDOWN,
        S_BFG,
        S_BFG1,
        S_BFGFLASH1
    },
    {
        // chainsaw
        am_noammo,
        S_SAWUP,
        S_SAWDOWN,
        S_SAW,
        S_SAW1,
        S_NULL
    },
    {
        // super shotgun
        am_shell,
        S_MODSPARE237,
        S_MODSPARE239,
        S_MODSPARE236,
        S_MODSPARE241,
        S_LIGHTDONE
    },
    {
        // extra weapon 0 (unused unless a mod transplants one here)
        am_clip,
        S_MODSPARE295,
        S_MODSPARE297,
        S_MODSPARE294,
        S_MODSPARE300,
        S_LIGHTDONE
    },
    {
        // extra weapon 1 (unused unless a mod transplants one here)
        am_clip,
        S_MODSPARE353,
        S_MODSPARE355,
        S_MODSPARE352,
        S_MODSPARE358,
        S_LIGHTDONE
    },
    {
        // extra weapon 2 (unused unless a mod transplants one here)
        am_rifle,
        S_MODSPARE407,
        S_MODSPARE409,
        S_MODSPARE406,
        S_MODSPARE411,
        S_LIGHTDONE
    },
    {
        // extra weapon 3 (unused unless a mod transplants one here)
        am_clip,
        S_MODSPARE464,
        S_MODSPARE466,
        S_MODSPARE463,
        S_MODSPARE469,
        S_LIGHTDONE
    },
    {
        // extra weapon 4 (unused unless a mod transplants one here)
        am_shell,
        S_MODSPARE511,
        S_MODSPARE513,
        S_MODSPARE510,
        S_MODSPARE515,
        S_LIGHTDONE
    },
    {
        // extra weapon 5 (unused unless a mod transplants one here)
        am_rifle,
        S_MODSPARE599,
        S_MODSPARE601,
        S_MODSPARE598,
        S_MODSPARE603,
        S_LIGHTDONE
    },
};

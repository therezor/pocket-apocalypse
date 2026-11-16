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
 *      Weapon sprite animation, weapon objects.
 *      Action functions for weapons.
 *
 *-----------------------------------------------------------------------------*/

#include "doomstat.h"
#include "r_main.h"
#include "p_map.h"
#include "p_inter.h"
#include "p_pspr.h"
#include "p_enemy.h"
#include "m_random.h"
#include "s_sound.h"
#include "sounds.h"
#include "d_event.h"

#include "global_data.h"

#define LOWERSPEED   (FRACUNIT*6)
#define RAISESPEED   (FRACUNIT*6)
#define WEAPONBOTTOM (FRACUNIT*128)
#define WEAPONTOP    (FRACUNIT*32)

#define BFGCELLS bfgcells        /* Ty 03/09/98 externalized in p_inter.c */

extern void P_Thrust(player_t *, angle_t, fixed_t);

//
// P_SetPsprite
//

static void P_SetPsprite(player_t *player, int position, statenum_t stnum)
{
  pspdef_t *psp = &player->psprites[position];

  do
    {
      const state_t *state;

      if (!stnum)
        {
          // object removed itself
          psp->state = NULL;
          break;
        }

      state = &states[stnum];
      psp->state = state;
      psp->tics = state->tics;        // could be 0

      if (state->misc1)
        {
          // coordinate set
          psp->sx = state->misc1 << FRACBITS;
          psp->sy = state->misc2 << FRACBITS;
        }

#ifdef SIM_TRACE
      printf("psp %d state %d tics %d ready %d pending %d\n", position, (int)stnum, state->tics, player->readyweapon, player->pendingweapon);
#endif
      // Call action routine.
      // Modified handling.
      if (state->action)
        {
          state->action(player, psp);
          if (!psp->state)
            break;
        }
      stnum = psp->state->nextstate;
    }
  while (!psp->tics);     // an initial state of 0 could cycle through
}

//
// P_BringUpWeapon
// Starts bringing the pending weapon up
// from the bottom of the screen.
// Uses player
//

static void P_BringUpWeapon(player_t *player)
{
  statenum_t newstate;

  if (player->pendingweapon == wp_nochange)
    player->pendingweapon = player->readyweapon;

  if (player->pendingweapon == wp_chainsaw)
    S_StartSound (player->mo, sfx_sawup);

  newstate = weaponinfo[player->pendingweapon].upstate;

  player->pendingweapon = wp_nochange;
  // killough 12/98: prevent pistol from starting visibly at bottom of screen:
  player->psprites[ps_weapon].sy =
WEAPONBOTTOM+FRACUNIT*2;

  P_SetPsprite(player, ps_weapon, newstate);
}

// The first set is where the weapon preferences from             // killough,
// default.cfg are stored. These values represent the keys used   // phares
// in DOOM2 to bring up the weapon, i.e. 6 = plasma gun. These    //    |
// are NOT the wp_* constants.                                    //    V

const int weapon_preferences[NUMWEAPONS+1] =
{
    6, 9, 4, 3, 2, 8, 5, 7, 1,  // !compatibility preferences
};

// P_SwitchWeapon checks current ammo levels and gives you the
// most preferred weapon with ammo. It will not pick the currently
// raised weapon. When called from P_CheckAmmo this won't matter,
// because the raised weapon has no ammo anyway. When called from
// G_BuildTiccmd you want to toggle to a different weapon regardless.

int P_SwitchWeapon(player_t *player)
{
  const int *prefer = &weapon_preferences[0]; // killough 3/22/98
  int currentweapon = player->readyweapon;
  int newweapon = currentweapon;
  int i = NUMWEAPONS+1;   // killough 5/2/98

  // killough 2/8/98: follow preferences and fix BFG/SSG bugs

  do
    switch (*prefer++)
      {
      case 1:
        if (!player->powers[pw_strength])      // allow chainsaw override
          break;
      case 0:
        newweapon = wp_fist;
        break;
      case 2:
        if (player->ammo[am_clip])
          newweapon = wp_pistol;
        break;
      case 3:
        if (player->weaponowned[wp_shotgun] && player->ammo[am_shell])
          newweapon = wp_shotgun;
        break;
      case 4:
        if (player->weaponowned[wp_chaingun] && player->ammo[am_clip])
          newweapon = wp_chaingun;
        break;
      case 5:
        if (player->weaponowned[wp_missile] && player->ammo[am_misl])
          newweapon = wp_missile;
        break;
      case 6:
        if (player->weaponowned[wp_plasma] && player->ammo[am_cell] &&
            _g->gamemode != shareware)
          newweapon = wp_plasma;
        break;
      case 7:
        if (player->weaponowned[wp_bfg] && _g->gamemode != shareware &&
            player->ammo[am_cell] >= (40))
          newweapon = wp_bfg;
        break;
      case 8:
        if (player->weaponowned[wp_chainsaw])
          newweapon = wp_chainsaw;
        break;
      case 9:
        if (player->weaponowned[wp_supershotgun] && _g->gamemode == commercial &&
            player->ammo[am_shell] >= (2))
          newweapon = wp_supershotgun;
        break;
      }
  while (newweapon==currentweapon && --i);          // killough 5/2/98
  return newweapon;
}

// killough 5/2/98: whether consoleplayer prefers weapon w1 over weapon w2.
int P_WeaponPreferred(int w1, int w2)
{
  return
    (weapon_preferences[0] != ++w2 && (weapon_preferences[0] == ++w1 ||
    (weapon_preferences[1] !=   w2 && (weapon_preferences[1] ==   w1 ||
    (weapon_preferences[2] !=   w2 && (weapon_preferences[2] ==   w1 ||
    (weapon_preferences[3] !=   w2 && (weapon_preferences[3] ==   w1 ||
    (weapon_preferences[4] !=   w2 && (weapon_preferences[4] ==   w1 ||
    (weapon_preferences[5] !=   w2 && (weapon_preferences[5] ==   w1 ||
    (weapon_preferences[6] !=   w2 && (weapon_preferences[6] ==   w1 ||
    (weapon_preferences[7] !=   w2 && (weapon_preferences[7] ==   w1
   ))))))))))))))));
}

// Weapon slots (the 1-7 keys): vanilla weapons, then the mod's extra ones
// (MOD_WEAPON_SLOTS / MOD_WEAPON_AMMO from tools/deh2c.py transplants).
#ifndef MOD_WEAPON_SLOTS
#define MOD_WEAPON_SLOTS 0, 0, 0, 0, 0, 0
#endif
#ifndef MOD_VANILLA_SLOTS       // a mod can take vanilla weapons out (slot 0)
#define MOD_VANILLA_SLOTS 1, 2, 3, 4, 5, 6, 7, 1, 3
#endif
#ifndef MOD_WEAPON_AMMO
#define MOD_WEAPON_AMMO 1, 1, 1, 1, 1, 1
#endif

const unsigned char weapon_slot[NUMWEAPONS] = { MOD_VANILLA_SLOTS, MOD_WEAPON_SLOTS };
static const unsigned char extra_ammo_per_shot[NUMWEAPONS - wp_extra0] = { MOD_WEAPON_AMMO };

int P_AmmoPerShot(int weapon)
{
    if (weapon == wp_bfg)
        return BFGCELLS;
    if (weapon == wp_supershotgun)
        return 2;
    if (weapon >= wp_extra0)
        return extra_ammo_per_shot[weapon - wp_extra0];
    return 1;
}

int P_CheckCanSwitchWeapon(weapontype_t weapon, player_t* player)
{
    const ammotype_t ammo = weaponinfo[weapon].ammo;

    if (ammo == am_noammo || player->ammo[ammo] >= P_AmmoPerShot(weapon))
        return weapon;

    return wp_nochange;
}

// The weapons of a slot (0: all slots), in cycling order: by slot, vanilla
// weapons before extras. first: one to put first (chainsaw/SSG for keys 1/3).
static int P_SlotWeapons(int slot, int first, int* list)
{
    int n = 0;

    if (first != wp_nochange)
        list[n++] = first;

    for (int s = 1; s <= 7; s++)
        if (!slot || s == slot)
            for (int w = 0; w < NUMWEAPONS; w++)
                if (weapon_slot[w] == s && w != first)
                    list[n++] = w;
    return n;
}

static int P_WeaponCycle(player_t *player, int dir)
{
    int list[NUMWEAPONS];
    const int n = P_SlotWeapons(0, wp_nochange, list);
    int i = 0;

    while (i < n && list[i] != player->readyweapon)
        i++;

    for (int k = 1; k <= n; k++)
    {
        const int w = list[((i + dir*k) % n + n) % n];

        if (player->weaponowned[w] && P_CheckCanSwitchWeapon(w, player) != wp_nochange)
            return w;
    }

    return player->readyweapon;
}

int P_WeaponCycleUp(player_t *player)
{
    return P_WeaponCycle(player, 1);
}

int P_WeaponCycleDown(player_t *player)
{
    return P_WeaponCycle(player, -1);
}

// Weapon key `slot` pressed: the next owned weapon of that slot after the
// raised (or coming) one; from another slot, the chainsaw / SSG first as in
// vanilla.
int P_WeaponForSlot(player_t *player, int slot)
{
    int list[NUMWEAPONS];
    const int first = slot == 1 ? wp_chainsaw : slot == 3 ? wp_supershotgun : wp_nochange;
    const int n = P_SlotWeapons(slot, first, list);
    const int cur = player->pendingweapon != wp_nochange ? player->pendingweapon : player->readyweapon;
    int i = -1;

    for (int k = 0; k < n; k++)
        if (list[k] == cur)
            i = k;

    for (int k = 1; k <= n; k++)
    {
        const int w = list[(i + k) % n];

        if (player->weaponowned[w] && w != cur)
            return w;
    }

    return wp_nochange;
}

//
// P_CheckAmmo
// Returns true if there is enough ammo to shoot.
// If not, selects the next weapon to use.
// (only in demo_compatibility mode -- killough 3/22/98)
//

boolean P_CheckAmmo(player_t *player)
{
  ammotype_t ammo = weaponinfo[player->readyweapon].ammo;
  int count = P_AmmoPerShot(player->readyweapon);  // Minimal amount for one shot varies.

  // Some do not need ammunition anyway.
  // Return if current ammunition sufficient.

  if (ammo == am_noammo || player->ammo[ammo] >= count)
    return true;

  return false;
}

//
// P_FireWeapon.
//

// Magazines (MOD_WEAPON_MAG from tools/deh2c.py zweapons): the ammo count
// stays the total; mag[] is how much of it is loaded. Firing empties the
// magazine, the reload animation (R key, or firing when empty) ends with
// A_LoadMag.
typedef struct { short weapon, size, reloadstate; } weapon_mag_t;
#ifdef MOD_WEAPON_MAG
static const weapon_mag_t weapon_mags[] = { MOD_WEAPON_MAG };
#endif

static const weapon_mag_t* P_Mag(int weapon)
{
#ifdef MOD_WEAPON_MAG
  for (unsigned i = 0; i < sizeof(weapon_mags)/sizeof(weapon_mags[0]); i++)
    if (weapon_mags[i].weapon == weapon)
      return &weapon_mags[i];
#endif
  return NULL;
}

int P_MagSize(int weapon)
{
  const weapon_mag_t* m = P_Mag(weapon);
  return m ? m->size : 0;
}

// Start the reload animation if the magazine can take more.
static boolean P_StartReload(player_t *player)
{
  const int w = player->readyweapon;
  const weapon_mag_t* m = P_Mag(w);
  const int ammo = m ? player->ammo[weaponinfo[w].ammo] : 0;

  if (!m || player->mag[w] >= m->size || ammo <= player->mag[w])
    return false;
  P_SetPsprite(player, ps_weapon, m->reloadstate);
  return true;
}

// MOD_PSPR_OVERRIDES kinds (tools/deh2c.py), see P_PsprOverride
enum { PSPR_SFX, PSPR_FLASHOFS, PSPR_SPAWN, PSPR_LOOP };

static int P_PsprOverride(const pspdef_t* psp, int kind, int from, int dflt);

// Shell by shell: one round per pass through the insert animation, which
// repeats (MOD_PSPR_OVERRIDES PSPR_LOOP) until the magazine is full or the
// ammo runs out.
void A_LoadOne(player_t *player, pspdef_t *psp)
{
  const int w = player->readyweapon;
  const int size = P_MagSize(w);
  const int ammo = player->ammo[weaponinfo[w].ammo];

  if (size && player->mag[w] < size && ammo > player->mag[w])
    player->mag[w]++;

  if (player->mag[w] < size && ammo > player->mag[w])
  {
    const int loop = P_PsprOverride(psp, PSPR_LOOP, 0, -1);

    if (loop >= 0)
      P_SetPsprite(player, ps_weapon, loop);
  }
}

void A_LoadMag(player_t *player, pspdef_t *psp)
{
  const int w = player->readyweapon;
  const int size = P_MagSize(w);
  const int ammo = player->ammo[weaponinfo[w].ammo];

  if (size)
    player->mag[w] = ammo < size ? ammo : size;
}

static void P_FireWeapon(player_t *player)
{
  statenum_t newstate;

  if (!P_CheckAmmo(player))
    return;

  {
    const int w = player->readyweapon;

    if (P_MagSize(w))
    {
      if (player->mag[w] > player->ammo[weaponinfo[w].ammo])
        player->mag[w] = player->ammo[weaponinfo[w].ammo];
      if (player->mag[w] <= 0)
      {
        P_StartReload(player);
        return;
      }
      player->mag[w]--;
    }
  }

  P_SetMobjState(player->mo, S_PLAY_ATK1);
  newstate = weaponinfo[player->readyweapon].atkstate;
  P_SetPsprite(player, ps_weapon, newstate);
  P_NoiseAlert(player->mo, player->mo);
}

//
// P_DropWeapon
// Player died, so put the weapon away.
//

void P_DropWeapon(player_t *player)
{
  P_SetPsprite(player, ps_weapon, weaponinfo[player->readyweapon].downstate);
}

//
// A_WeaponReady
// The player can fire the weapon
// or change to another weapon at this time.
// Follows after getting weapon up,
// or after previous attack/fire sequence.
//

void A_WeaponReady(player_t *player, pspdef_t *psp)
{
  if (player->cmd.reload && player->pendingweapon == wp_nochange && P_StartReload(player))
    return;

  // get out of attack state
  if (player->mo->state == &states[S_PLAY_ATK1]
      || player->mo->state == &states[S_PLAY_ATK2] )
    P_SetMobjState(player->mo, S_PLAY);

  if (player->readyweapon == wp_chainsaw && psp->state == &states[S_SAW])
    S_StartSound(player->mo, sfx_sawidl);

  // check for change
  //  if player is dead, put the weapon away

  if (player->pendingweapon != wp_nochange || !player->health)
    {
      // change weapon (pending weapon should already be validated)
      statenum_t newstate = weaponinfo[player->readyweapon].downstate;
      P_SetPsprite(player, ps_weapon, newstate);
      return;
    }

  // check for fire
  //  the missile launcher and bfg do not auto fire

  if (player->cmd.buttons & BT_ATTACK)
    {
      if (!player->attackdown || (player->readyweapon != wp_missile &&
                                  player->readyweapon != wp_bfg))
        {
          player->attackdown = true;
          P_FireWeapon(player);
          return;
        }
    }
  else
    player->attackdown = false;

  // bob the weapon based on movement speed
  {
    int angle = (128*_g->leveltime) & FINEMASK;
    psp->sx = FRACUNIT + FixedMul(player->bob, finecosine[angle]);
    angle &= FINEANGLES/2-1;
    psp->sy = WEAPONTOP + FixedMul(player->bob, finesine[angle]);
  }
}

//
// A_ReFire
// The player can re-fire the weapon
// without lowering it entirely.
//

void A_ReFire(player_t *player, pspdef_t *psp)
{
  // check for fire
  //  (if a weaponchange is pending, let it go through instead)

  if ( (player->cmd.buttons & BT_ATTACK)
       && player->pendingweapon == wp_nochange && player->health)
    {
      player->refire++;
      P_FireWeapon(player);
    }
  else
    {
      player->refire = 0;
      P_CheckAmmo(player);
    }
}

void A_CheckReload(player_t *player, pspdef_t *psp)
{
  if (!P_CheckAmmo(player))
  {
    /* cph 2002/08/08 - In old Doom, P_CheckAmmo would start the weapon lowering
     * immediately. This was lost in Boom when the weapon switching logic was
     * rewritten. But we must tell Doom that we don't need to complete the
     * reload frames for the weapon here. G_BuildTiccmd will set ->pendingweapon
     * for us later on. */
    P_SetPsprite(player,ps_weapon,weaponinfo[player->readyweapon].downstate);
  }
}

//
// A_Lower
// Lowers current weapon,
//  and changes weapon at bottom.
//

void A_Lower(player_t *player, pspdef_t *psp)
{
  psp->sy += LOWERSPEED;

  // Is already down.
  if (psp->sy < WEAPONBOTTOM)
    return;

  // Player is dead.
  if (player->playerstate == PST_DEAD)
    {
      psp->sy = WEAPONBOTTOM;
      return;      // don't bring weapon back up
    }

  // The old weapon has been lowered off the screen,
  // so change the weapon and start raising it

  if (!player->health)
    {      // Player is dead, so keep the weapon off screen.
      P_SetPsprite(player,  ps_weapon, S_NULL);
      return;
    }

  player->readyweapon = player->pendingweapon;

  P_BringUpWeapon(player);
}

//
// A_Raise
//

void A_Raise(player_t *player, pspdef_t *psp)
{
  statenum_t newstate;

  psp->sy -= RAISESPEED;

  if (psp->sy > WEAPONTOP)
    return;

  psp->sy = WEAPONTOP;

  // The weapon has been raised all the way,
  //  so change to the ready state.

  newstate = weaponinfo[player->readyweapon].readystate;

  P_SetPsprite(player, ps_weapon, newstate);
}


// Weapon states that tools/deh2c.py relocated into S_MODSPARE* (a weapon
// transplant, MOD_PSPR_OVERRIDES in mod_gen.h) keep the behaviour their
// original state numbers gave them: the sound a renamed action plays, and the
// flash offset A_FireCGun derives from the state number.

typedef struct { short state, kind, from, to; } pspr_override_t;

#ifdef MOD_PSPR_OVERRIDES
static const pspr_override_t pspr_overrides[] = { MOD_PSPR_OVERRIDES };
#endif

static int P_PsprOverride(const pspdef_t* psp, int kind, int from, int dflt)
{
#ifdef MOD_PSPR_OVERRIDES
  int st = psp->state - states;

  for (unsigned i = 0; i < sizeof(pspr_overrides) / sizeof(pspr_overrides[0]); i++)
    if (pspr_overrides[i].state == st && pspr_overrides[i].kind == kind && pspr_overrides[i].from == from)
      return pspr_overrides[i].to;
#endif
  return dflt;
}

int P_WeaponSfx(const pspdef_t* psp, int sfx)
{
  return P_PsprOverride(psp, PSPR_SFX, sfx, sfx);
}

// Projectile a transplanted weapon fires (its own copy of MT_ROCKET etc.)
static mobjtype_t P_WeaponSpawn(const pspdef_t* psp, mobjtype_t type)
{
  return (mobjtype_t)P_PsprOverride(psp, PSPR_SPAWN, type, type);
}

// Weapons now recoil, amount depending on the weapon.              // phares
//                                                                  //   |
// The P_SetPsprite call in each of the weapon firing routines      //   V
// was moved here so the recoil could be synched with the
// muzzle flash, rather than the pressing of the trigger.
// The BFG delay caused this to be necessary.

static void A_FireSomething(player_t* player,int adder)
{
  P_SetPsprite(player, ps_flash,
               weaponinfo[player->readyweapon].flashstate+adder);
}

//
// A_GunFlash
//

void A_GunFlash(player_t *player, pspdef_t *psp)
{
  P_SetMobjState(player->mo, S_PLAY_ATK2);

  A_FireSomething(player,0);                                      // phares
}

//
// WEAPON ATTACKS
//

//
// A_Punch
//

// A mod melee weapon's own damage range (MOD_WEAPON_PUNCH: {weapon, min, max}).
typedef struct { short weapon, min, max; } weapon_punch_t;
#ifdef MOD_WEAPON_PUNCH
static const weapon_punch_t weapon_punches[] = { MOD_WEAPON_PUNCH };
#endif

void A_Punch(player_t *player, pspdef_t *psp)
{
  angle_t angle;
  int t, slope, damage = (P_Random()%10+1)<<1;

#ifdef MOD_WEAPON_PUNCH
  for (unsigned i = 0; i < sizeof(weapon_punches)/sizeof(weapon_punches[0]); i++)
    if (weapon_punches[i].weapon == player->readyweapon)
      damage = weapon_punches[i].min + P_Random() % (weapon_punches[i].max - weapon_punches[i].min + 1);
#endif

  if (player->powers[pw_strength])
    damage *= 10;

  angle = player->mo->angle;

  // killough 5/5/98: remove dependence on order of evaluation:
  t = P_Random();
  angle += (t - P_Random())<<18;

  /* killough 8/2/98: make autoaiming prefer enemies */
  if (
      (slope = P_AimLineAttack(player->mo, angle, MELEERANGE, MF_FRIEND),
       !_g->linetarget))
    slope = P_AimLineAttack(player->mo, angle, MELEERANGE, 0);

  P_LineAttack(player->mo, angle, MELEERANGE, slope, damage);

  if (!_g->linetarget)
    return;

  S_StartSound(player->mo, sfx_punch);

  // turn to face target

  player->mo->angle = R_PointToAngle2(player->mo->x, player->mo->y,
                                      _g->linetarget->x, _g->linetarget->y);
}

//
// A_Saw
//

void A_Saw(player_t *player, pspdef_t *psp)
{
  int slope, damage = 2*(P_Random()%10+1);
  angle_t angle = player->mo->angle;
  // killough 5/5/98: remove dependence on order of evaluation:
  int t = P_Random();
  angle += (t - P_Random())<<18;

  /* Use meleerange + 1 so that the puff doesn't skip the flash
   * killough 8/2/98: make autoaiming prefer enemies */
  if (
      (slope = P_AimLineAttack(player->mo, angle, MELEERANGE+1, MF_FRIEND),
       !_g->linetarget))
    slope = P_AimLineAttack(player->mo, angle, MELEERANGE+1, 0);

  P_LineAttack(player->mo, angle, MELEERANGE+1, slope, damage);

  if (!_g->linetarget)
    {
      S_StartSound(player->mo, sfx_sawful);
      return;
    }

  S_StartSound(player->mo, sfx_sawhit);

  // turn to face target
  angle = R_PointToAngle2(player->mo->x, player->mo->y,
                          _g->linetarget->x, _g->linetarget->y);

  if (angle - player->mo->angle > ANG180) {
    if (angle - player->mo->angle < -ANG90/20)
      player->mo->angle = angle + ANG90/21;
    else
      player->mo->angle -= ANG90/20;
  } else {
    if (angle - player->mo->angle > ANG90/20)
      player->mo->angle = angle - ANG90/21;
    else
      player->mo->angle += ANG90/20;
  }

  player->mo->flags |= MF_JUSTATTACKED;
}

//
// A_FireMissile
//

void A_FireMissile(player_t *player, pspdef_t *psp)
{
  S_StartSound(player->mo, P_WeaponSfx(psp, sfx_rlaunc));
  player->ammo[weaponinfo[player->readyweapon].ammo]--;
  P_SpawnPlayerMissile(player->mo, P_WeaponSpawn(psp, MT_ROCKET));
}

//
// A_FireBFG
//

void A_FireBFG(player_t *player, pspdef_t *psp)
{
  player->ammo[weaponinfo[player->readyweapon].ammo] -= P_AmmoPerShot(player->readyweapon);
  P_SpawnPlayerMissile(player->mo, P_WeaponSpawn(psp, MT_BFG));
}

//
// A_FirePlasma
//

void A_FirePlasma(player_t *player, pspdef_t *psp)
{
  S_StartSound(player->mo, P_WeaponSfx(psp, sfx_plasma));
  player->ammo[weaponinfo[player->readyweapon].ammo]--;

  A_FireSomething(player,P_Random()&1);              // phares
  P_SpawnPlayerMissile(player->mo, P_WeaponSpawn(psp, MT_PLASMA));
}


//
// P_BulletSlope
// Sets a slope so a near miss is at aproximately
// the height of the intended target
//
static void P_BulletSlope(mobj_t *mo)
{
  angle_t an = mo->angle;    // see which target is to be aimed at

  /* killough 8/2/98: make autoaiming prefer enemies */
  unsigned int mask = MF_FRIEND;

  do
    {
      _g->bulletslope = P_AimLineAttack(mo, an, 16*64*FRACUNIT, mask);
      if (!_g->linetarget)
  _g->bulletslope = P_AimLineAttack(mo, an += 1<<26, 16*64*FRACUNIT, mask);
      if (!_g->linetarget)
  _g->bulletslope = P_AimLineAttack(mo, an -= 2<<26, 16*64*FRACUNIT, mask);
    }
  while (mask && (mask=0, !_g->linetarget));  /* killough 8/2/98 */

  // No autoaim target: shoot where the player looks.
  if (!_g->linetarget && P_MobjIsPlayer(mo))
    _g->bulletslope = P_LookSlope(P_MobjIsPlayer(mo));
}

//
// P_GunShot
//

static void P_GunShot(mobj_t *mo, boolean accurate)
{
  int damage = 5*(P_Random()%3+1);
  angle_t angle = mo->angle;

  if (!accurate)
    {  // killough 5/5/98: remove dependence on order of evaluation:
      int t = P_Random();
      angle += (t - P_Random())<<18;
    }

  P_LineAttack(mo, angle, MISSILERANGE, _g->bulletslope, damage);
}

// Bullets with the weapon's own damage, pellet count and spread
// (MOD_WEAPON_FIRE: damage is fixed, as GZDoom's FBF_NORANDOM).
typedef struct { short weapon, damage, pellets; int spread; } weapon_fire_t;
#ifdef MOD_WEAPON_FIRE
static const weapon_fire_t weapon_fires[] = { MOD_WEAPON_FIRE };
#endif

void A_FireMod(player_t *player, pspdef_t *psp)
{
  const int w = player->readyweapon;
  const ammotype_t ammo = weaponinfo[w].ammo;
  int damage = 10, pellets = 1, spread = 0;

#ifdef MOD_WEAPON_FIRE
  for (unsigned i = 0; i < sizeof(weapon_fires)/sizeof(weapon_fires[0]); i++)
    if (weapon_fires[i].weapon == w)
    {
      damage = weapon_fires[i].damage;
      pellets = weapon_fires[i].pellets;
      spread = weapon_fires[i].spread;
    }
#endif

  if (ammo != am_noammo)
  {
    if (player->ammo[ammo] <= 0)
      return;
    player->ammo[ammo]--;
  }

  P_SetMobjState(player->mo, S_PLAY_ATK2);
  P_BulletSlope(player->mo);

  for (int i = 0; i < pellets; i++)
  {
    angle_t angle = player->mo->angle;

    if (spread)
    {
      int t = P_Random();
      angle += (t - P_Random()) * spread;
    }
    P_LineAttack(player->mo, angle, MISSILERANGE, _g->bulletslope, damage);
  }
}

void A_WeaponSound(player_t *player, pspdef_t *psp)
{
  const int sfx = P_WeaponSfx(psp, sfx_None);

  // No origin: the player's own gun, at full volume, and a shot isn't cut
  // off by the next sound of the same weapon (cocking, a shell, a click) -
  // sounds from one origin replace each other.
  if (sfx != sfx_None)
    S_StartSound(NULL, sfx);
}

//
// A_FirePistol
//

void A_FirePistol(player_t *player, pspdef_t *psp)
{
  S_StartSound(player->mo, P_WeaponSfx(psp, sfx_pistol));

  P_SetMobjState(player->mo, S_PLAY_ATK2);
  player->ammo[weaponinfo[player->readyweapon].ammo]--;

  A_FireSomething(player,0);                                      // phares
  P_BulletSlope(player->mo);
  P_GunShot(player->mo, !player->refire);
}

//
// A_FireShotgun
//

void A_FireShotgun(player_t *player, pspdef_t *psp)
{
  int i;

  S_StartSound(player->mo, P_WeaponSfx(psp, sfx_shotgn));
  P_SetMobjState(player->mo, S_PLAY_ATK2);

  player->ammo[weaponinfo[player->readyweapon].ammo]--;

  A_FireSomething(player,0);                                      // phares

  P_BulletSlope(player->mo);

  for (i=0; i<7; i++)
    P_GunShot(player->mo, false);
}

//
// A_FireShotgun2
//

void A_FireShotgun2(player_t *player, pspdef_t *psp)
{
  int i;

  S_StartSound(player->mo, P_WeaponSfx(psp, sfx_dshtgn));
  P_SetMobjState(player->mo, S_PLAY_ATK2);
  player->ammo[weaponinfo[player->readyweapon].ammo] -= 2;

  A_FireSomething(player,0);                                      // phares

  P_BulletSlope(player->mo);

  for (i=0; i<20; i++)
    {
      int damage = 5*(P_Random()%3+1);
      angle_t angle = player->mo->angle;
      // killough 5/5/98: remove dependence on order of evaluation:
      int t = P_Random();
      angle += (t - P_Random())<<19;
      t = P_Random();
      P_LineAttack(player->mo, angle, MISSILERANGE, _g->bulletslope +
                   ((t - P_Random())<<5), damage);
    }
}

//
// A_FireCGun
//

void A_FireCGun(player_t *player, pspdef_t *psp)
{
  if (player->ammo[weaponinfo[player->readyweapon].ammo])
    S_StartSound(player->mo, P_WeaponSfx(psp, sfx_pistol));

  if (!player->ammo[weaponinfo[player->readyweapon].ammo])
    return;

  P_SetMobjState(player->mo, S_PLAY_ATK2);
  player->ammo[weaponinfo[player->readyweapon].ammo]--;

  A_FireSomething(player,P_PsprOverride(psp, PSPR_FLASHOFS, 0,
                                         psp->state - &states[S_CHAIN1]));  // phares

  P_BulletSlope(player->mo);

  P_GunShot(player->mo, !player->refire);
}

void A_Light0(player_t *player, pspdef_t *psp)
{
  player->extralight = 0;
}

void A_Light1 (player_t *player, pspdef_t *psp)
{
  player->extralight = 1;
}

void A_Light2 (player_t *player, pspdef_t *psp)
{
  player->extralight = 2;
}

//
// A_BFGSpray
// Spawn a BFG explosion on every monster in view
//

void A_BFGSpray(mobj_t *mo)
{
  int i;

  for (i=0 ; i<40 ; i++)  // offset angles from its attack angle
    {
      int j, damage;
      angle_t an = mo->angle - ANG90/2 + ANG90/40*i;

      // mo->target is the originator (player) of the missile

      // killough 8/2/98: make autoaiming prefer enemies
      if (
         (P_AimLineAttack(mo->target, an, 16*64*FRACUNIT, MF_FRIEND),
         !_g->linetarget))
        P_AimLineAttack(mo->target, an, 16*64*FRACUNIT, 0);

      if (!_g->linetarget)
        continue;

      P_SpawnMobj(_g->linetarget->x, _g->linetarget->y,
                  _g->linetarget->z + (_g->linetarget->height>>2), MT_EXTRABFG);

      for (damage=j=0; j<15; j++)
        damage += (P_Random()&7) + 1;

      P_DamageMobj(_g->linetarget, mo->target, mo->target, damage);
    }
}

//
// A_BFGsound
//

void A_BFGsound(player_t *player, pspdef_t *psp)
{
  S_StartSound(player->mo, P_WeaponSfx(psp, sfx_bfg));
}

//
// P_SetupPsprites
// Called at start of level for each player.
//

void P_SetupPsprites(player_t *player)
{
  int i;

  // remove all psprites
  for (i=0; i<NUMPSPRITES; i++)
    player->psprites[i].state = NULL;

  // spawn the gun
  player->pendingweapon = player->readyweapon;
  P_BringUpWeapon(player);
}

//
// P_MovePsprites
// Called every tic by player thinking routine.
//

void P_MovePsprites(player_t *player)
{
  pspdef_t *psp = player->psprites;
  int i;

  // a null state means not active
  // drop tic count and possibly change state
  // a -1 tic count never changes

  for (i=0; i<NUMPSPRITES; i++, psp++)
    if (psp->state && psp->tics != -1 && !--psp->tics)
      P_SetPsprite(player, i, psp->state->nextstate);

  player->psprites[ps_flash].sx = player->psprites[ps_weapon].sx;
  player->psprites[ps_flash].sy = player->psprites[ps_weapon].sy;
}

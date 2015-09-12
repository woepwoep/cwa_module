# -*- coding: utf-8 -*-
from openerp import models, fields, api
import ftplib
import os
import re
import math
from lxml import etree
import types
import datetime
from constants import *
import logging
_logger = logging.getLogger(__name__)

#############################################################################################################
#                                                                                                           #
#                           These two functions are copied from the product model                           #
#                                                                                                           #
#############################################################################################################
def sanitize_ean13(ean13):
    """Creates and returns a valid ean13 from an invalid one"""
    if not ean13:
        return "0000000000000"
    ean13 = re.sub("[A-Za-z]","0",ean13);
    ean13 = re.sub("[^0-9]","",ean13);
    ean13 = ean13[:13]
    if len(ean13) < 13:
        ean13 = ean13 + '0' * (13-len(ean13))
    return ean13[:-1] + str(ean_checksum(ean13))

def ean_checksum(eancode):
    """returns the checksum of an ean string of length 13, returns -1 if the string has the wrong length"""
    if len(eancode) != 13:
        return -1
    oddsum=0
    evensum=0
    total=0
    eanvalue=eancode
    reversevalue = eanvalue[::-1]
    finalean=reversevalue[1:]
    
    for i in range(len(finalean)):
        if i % 2 == 0:
            oddsum += int(finalean[i])
        else:
            evensum += int(finalean[i])
    total=(oddsum * 3) + evensum
    
    check = int(10 - math.ceil(total % 10.0)) %10
    return check

#############################################################################################################

class cwa_import_module(models.Model):
    _name = 'cwa.import'
        
    def connect_to_ftp(self, address, usr, pwd):
        ftp = ftplib.FTP(address)
        ftp.login(usr, pwd)
        return ftp
    
    def disconnect_from_ftp(self, ftp):
        ftp.quit()
        return True
        
    def download_ftp_files(self, tmp, ftp, todo, done):
        ftp.cwd(done)
        processed_files = ftp.nlst()
        ftp.cwd(todo)
        todo_files = ftp.nlst()
        if not os.path.exists('/tmp/%s' % tmp):
            os.mkdir('/tmp/%s' % tmp)
        for f in todo_files:
            if f not in processed_files:
                ftp.retrbinary("RETR %s" % f, open('/tmp/%s/%s' % (tmp, f), 'wb').write)     
        return True
    
    def move_ftp_files(self, tmp, ftp, todo, done):
        processed_files = os.listdir('/tmp/%s' % tmp)
        for f in processed_files:
            ftp.rename('%s/%s' % (todo, f), '%s/%s' % (done, f))
        return True
    
    def parse_xml_products(self, f):
        products = []
        product_tags = ['id', 'name', 'list_price', 'ean13', 'categ_id/id', 'taxes_id', 'supplier_taxes_id', 'available_in_pos', 'uom_id/id', 'uom_po_id/id', 'pos_categ_id/id']
        root = etree.parse(f).getroot()
        
        for product in root.iter('product'):
            temp_data = {}
            for item in product:
                if item.tag not in product_tags:
                    product_tags.append(item.tag)
                if type(item.text) is types.NoneType:
                    temp_data[item.tag] = "NONE"
                else:
                    temp_data[item.tag] = item.text.encode('utf-8').upper()
                
            temp_data['id'] = self.set_external_id(temp_data)
            temp_data['ean13'] = self.set_ean_code(temp_data['eancode'])
            temp_data['name'] = temp_data['omschrijving']
            temp_data['list_price'] = float(temp_data['consumentenprijs'])
            temp_data['categ_id/id'] = "cwa_cbl_cat.%s" % temp_data['cblcode']
            temp_data['taxes_id'] = 'Verkopen/omzet hoog' if temp_data['btw'] == '21' else 'Verkopen/omzet laag'
            temp_data['supplier_taxes_id'] = 'BTW te vorderen hoog (inkopen)' if temp_data['btw'] == '21' else 'BTW te vorderen laag (inkopen)'
            temp_data['available_in_pos'] = 'false'
            temp_data['pos_categ_id/id'] = 'cwa_module.cwa_pos_categ_%s' % (temp_data['cblcode'][:5])
            try:
                temp_data['uom_id/id'] = uom_translations[temp_data['verpakkingce']]
                temp_data['uom_po_id/id'] = uom_translations[temp_data['verpakkingce']]
            except KeyError:
                temp_data['uom_id/id'] = uom_translations['STUKS']
                temp_data['uom_po_id/id'] = uom_translations['STUKS']
        
            temp_list = []
            for tag in product_tags:
                try:
                    temp_list.append(temp_data[tag])
                except KeyError:
                    temp_list.append("NONE")
            products.append(temp_list)
        return products, product_tags
    
    def parse_xml_supplier_info(self, f):
        root = etree.parse(f).getroot()
        supplier_info = []
        supplier_info_tags = ['id', 'name/id', 'product_tmpl_id/id', 'pos_categ_id']
        
        for product in root.iter('product'):
            temp_data = {}
            for item in product:
                if item.tag not in supplier_info_tags:
                    supplier_info_tags.append(item.tag)
                if type(item.text) is types.NoneType:
                    temp_data[item.tag] = "NONE"
                else:
                    temp_data[item.tag] = item.text.encode('utf-8').upper()
                    
            temp_data['id'] = 'supplier_info_%s_%s' % (temp_data['leveranciernummer'], temp_data['bestelnummer'])
            temp_data['name/id'] = 'cwa_module.supplier_code_%s' % (temp_data['leveranciernummer'])
            temp_data['product_tmpl_id/id'] = self.set_external_id(temp_data)
            temp_data['pos_categ_id'] = "cwa_module.cwa_pos_categ_%s" % temp_data['cblcode'][:5]
                
            temp_list = []
            for tag in supplier_info_tags:
                try:
                    temp_list.append(temp_data[tag])
                except KeyError:
                    temp_list.append("NONE")
            supplier_info.append(temp_list)
            #ex_id = 'supplier_info_%s_%s' % (temp_data['leveranciernummer'], temp_data['bestelnummer'])
            #name = 'cwa_module.supplier_code_%s' % (temp_data['leveranciernummer'])
            #temp_data['pid'] = self.set_external_id(temp_data)
            #supplier_info.append([ex_id, name, temp_data['pid'], temp_data['inkoopprijs'], temp_data['consumentenprijs'], temp_data['bestelnummer']])
        return supplier_info, supplier_info_tags
                
                
    def set_external_id(self, data):
        if data['eancode'] == 'None':
            return 'product_ex_id_%s_%s' % (data['leveranciernummer'], data['bestelnummer'])
        else:
            return 'product_ex_id_%s_%s' % (data['eancode'], data['verpakkingce'])
    
    def set_ean_code(self, ean):
        return sanitize_ean13(ean)
        """
        if ean == 'None':
            return 0
        elif ean[:2] == '21' or ean[:2] == '23':
            return sanitize_ean13(ean)
        else:
            if len(str(ean)) < 13:
                return ((13-len(str(ean))) * '0') + ean
            else:
                return ean"""
            
    def split_data(self, data):
        split_size = 50
        return [data[x:x+split_size] for x in range(0, len(data), split_size)]
        
    def load_records(self, cr, uid, tags, data, model):
        data = self.split_data(data)
        for d in data:
            new_cr = self.pool.cursor()
            x = self.pool.get(model).load(new_cr, uid, tags, d)
            new_cr.commit()
            new_cr.close()
            if len(x['messages']) > 0:
                _logger.error(x)
            else:
                _logger.warning(x)
        return True
    
    def gen_tmp_name(self):
        tmp = 'cwa_import_%s' % datetime.datetime.now().isoformat().replace(':', '').replace('-', '').replace('.', '')
        return tmp

    def write_log(self, log_data):
        with open('error_log.txt', 'a') as f:
            f.write(str(log_data)+'\n\n')
    
    def run(self, cr, uid):
        ''' 
        params[0] = ip address
        params[1] = uid
        params[2] = pwd
        params[3] = todo directory
        params[4] = done directory 
        '''
        _logger.warning("Getting arguments")
        params = self.pool['ir.config_parameter'].get_param(cr, uid, 'cwa.import.ftp_info').split(';')
        _logger.warning(params)
        _logger.warning("Connecting to ftp")
        ftp = self.connect_to_ftp(params[0], params[1], params[2]) # returns ftp connection instance
        tmp = self.gen_tmp_name()
        _logger.warning("Downloading files")
        self.download_ftp_files(tmp, ftp, params[3], params[4])
        self.disconnect_from_ftp(ftp)
        _logger.warning("Parsing files")
        for f in os.listdir('/tmp/%s' % tmp):
            _logger.warning("Parsing products")
            product_info = self.parse_xml_products('/tmp/%s/%s'%(tmp, f))
            _logger.warning("Parsing supplier info")
            supplier_info = self.parse_xml_supplier_info('/tmp/%s/%s'%(tmp, f))
            _logger.warning("Loading products")
            self.load_records(cr, uid, product_info[1], product_info[0], 'product.template')
            _logger.warning("Loading supplierinfo")
            self.load_records(cr, uid, supplier_info[1], supplier_info[0], 'product.supplierinfo')
        _logger.warning("Moving files")
        ftp = self.connect_to_ftp(params[0], params[1], params[2])
        self.move_ftp_files(tmp, ftp, params[3], params[4])
        ftp.quit()
        _logger.warning("Done")
        return True


class extended_supplierinfo(models.Model):
    _inherit = 'product.supplierinfo'
    
    eancode =           fields.Char('eancode', help="eancode")
    omschrijving =      fields.Char('omschrijving', help="omschrijving")
    weegschaalartikel = fields.Char('weegschaalartikel', help="1 = waar/0 = niet waar")
    wichtartikel =      fields.Char('wichtartikel', help="1 = waar/0 = niet waar")
    pluartikel =        fields.Char('pluartikel', help="1 = waar/0 = niet waar")
    inhoud =            fields.Char('inhoud', help="Inhoud van de verpakking.")
    eenheid =           fields.Char('eenheid', help="Aanduiding van de inhoud.")
    verpakkingce =      fields.Char('verpakkingce', help="Verpakking van consumenten eenheid.")
    merk =              fields.Char('merk', help="merk")
    kwaliteit =         fields.Char('kwaliteit', help="Kwaliteitsaanduiding")
    btw =               fields.Char('btw', help="BTW percentage 0, 6 of 21")
    cblcode =           fields.Char('cblcode', help="cblcode")
    leveranciernummer = fields.Char('leveranciernummer', help="Identificerend nummer van een leverancier.")
    bestelnummer =      fields.Char('bestelnummer', help="Bestelnummer van artikel bij leverancier.")
    proefdiervrij =     fields.Char('proefdiervrij', help="0=onbekend / 1=ja / 2=nee")
    vegetarisch =       fields.Char('vegetarisch', help="0=onbekend / 1=ja / 2=nee")
    veganistisch =      fields.Char('veganistisch', help="0=onbekend / 1=ja / 2=nee")
    rauwemelk =         fields.Char('rauwemelk', help="0=onbekend / 1=ja / 2=nee")
    inkoopprijs =       fields.Char('inkoopprijs', help="inkoopprijs")
    consumentenprijs =  fields.Char('consumentenprijs', help="consumentenprijs")
    ingangsdatum =      fields.Char('ingangsdatum', help="Datum in de vorm eejj-mm-dd")
    herkomst =          fields.Char('herkomst', help="Land van herkomst in vorm ISO 3166 code.")
    ingredienten =      fields.Char('ingredienten', help="Beschrijving van de ingredienten.")
    statiegeld =        fields.Char('statiegeld', help="bedrag")
    kassaomschrijving = fields.Char('kassaomschrijving', help="Korte omschrijving van het product tbv de kassa")
    plucode =           fields.Char('plucode', help="4cijferige plucode.")
    sve =               fields.Char('sve', help="Standaard verpakkings eenheid bij leverancier.")
    status =            fields.Char('status', help="Mogelijke waarden: Actief/Non Actief/Gesaneerd")
    keurmerkbio =       fields.Char('keurmerkbio', help="keurmerkbio")
    keurmerkoverig =    fields.Char('keurmerkoverig', help="keurmerkoverig")
    herkomstregio =     fields.Char('herkomstregio', help="herkokmstregio")
    dieetinformatie =   fields.Char('dieetinformatie', help="0 = onbekend / 1 = aanwezig / 2 = niet aanwezig / 3 = mogelijk aanwezig")
    aantaldagenhoudbaar=fields.Char('aantaldagenhoudbaar', help="aantaldagenhoudbaar")
    bewaartemperatuur = fields.Char('bewaartemperatuur', help="bewaartemperatuur")
    gebruikstips =      fields.Char('gebruikstips', help="gebruikstips")
    lengte =            fields.Char('lengte', help="lengte")
    breedte =           fields.Char('breedte', help="breedte")
    hoogte =            fields.Char('hoogte', help="hoogte")
    code =              fields.Char('code', help="code")
    d204 =              fields.Char('d204', help="Cacao")
    d209 =              fields.Char('d209', help="Glutamaat")
    d210 =              fields.Char('d210', help="Gluten")
    d212 =              fields.Char('d212', help="Ei")
    d213 =              fields.Char('d213', help="Kip")
    d214 =              fields.Char('d214', help="Melk")
    d234 =              fields.Char('d234', help="Koriander")
    d215 =              fields.Char('d215', help="Lactose")
    d239 =              fields.Char('d239', help="Lupine")
    d216 =              fields.Char('d216', help="Mais")
    d217 =              fields.Char('d217', help="Noten")
    d217b =             fields.Char('d217b', help="Notenolie")
    d220 =              fields.Char('d220', help="Peulvruchten")
    d221 =              fields.Char('d221', help="Pinda")
    d221b =             fields.Char('d221b', help="Pindaolie")
    d222 =              fields.Char('d222', help="Rogge")
    d223 =              fields.Char('d223', help="Rundvlees")
    d236 =              fields.Char('d236', help="Schaaldieren")
    d235 =              fields.Char('d235', help="Selderij")
    d238 =              fields.Char('d238', help="Sesam")
    d238b =             fields.Char('d238b', help="Sesamolie")
    d225 =              fields.Char('d225', help="Soja")
    d226 =              fields.Char('d226', help="Soja-olie")
    d228 =              fields.Char('d228', help="Sulfiet")
    d230 =              fields.Char('d230', help="Tarwe")
    d232 =              fields.Char('d232', help="Varkensvlees")
    d237 =              fields.Char('d237', help="Vis")
    d240 =              fields.Char('d240', help="Wortel")
    d241 =              fields.Char('d241', help="Mosterd")
    d242 =              fields.Char('d242', help="Weekdieren")
    pos_categ_id =      fields.Char('NOT A REFERENCE', help="Not a reference field, just a char field.")
    
    
class extended_template(models.Model):
    _inherit = 'product.template'

    eancode =           fields.Char('eancode', help="eancode")
    omschrijving =      fields.Char('omschrijving', help="omschrijving")
    weegschaalartikel = fields.Char('weegschaalartikel', help="1 = waar/0 = niet waar")
    wichtartikel =      fields.Char('wichtartikel', help="1 = waar/0 = niet waar")
    pluartikel =        fields.Char('pluartikel', help="1 = waar/0 = niet waar")
    inhoud =            fields.Char('inhoud', help="Inhoud van de verpakking.")
    eenheid =           fields.Char('eenheid', help="Aanduiding van de inhoud.")
    verpakkingce =      fields.Char('verpakkingce', help="Verpakking van consumenten eenheid.")
    merk =              fields.Char('merk', help="merk")
    kwaliteit =         fields.Char('kwaliteit', help="Kwaliteitsaanduiding")
    btw =               fields.Char('btw', help="BTW percentage 0, 6 of 21")
    cblcode =           fields.Char('cblcode', help="cblcode")
    leveranciernummer = fields.Char('leveranciernummer', help="Identificerend nummer van een leverancier.")
    bestelnummer =      fields.Char(compute="_compute_bestelnummer", help="Bestelnummer van artikel bij leverancier.")
    proefdiervrij =     fields.Char('proefdiervrij', help="0=onbekend / 1=ja / 2=nee")
    vegetarisch =       fields.Char('vegetarisch', help="0=onbekend / 1=ja / 2=nee")
    veganistisch =      fields.Char('veganistisch', help="0=onbekend / 1=ja / 2=nee")
    rauwemelk =         fields.Char('rauwemelk', help="0=onbekend / 1=ja / 2=nee")
    inkoopprijs =       fields.Float(compute="_compute_inkoopprijs", help="inkoopprijs")
    consumentenprijs =  fields.Float(compute="_compute_consumentenprijs", help="consumentenprijs")
    ingangsdatum =      fields.Char('ingangsdatum', help="Datum in de vorm eejj-mm-dd")
    herkomst =          fields.Char('herkomst', help="Land van herkomst in vorm ISO 3166 code.")
    ingredienten =      fields.Char('ingredienten', help="Beschrijving van de ingredienten.")
    statiegeld =        fields.Char('statiegeld', help="bedrag")
    kassaomschrijving = fields.Char('kassaomschrijving', help="Korte omschrijving van het product tbv de kassa")
    plucode =           fields.Char('plucode', help="4cijferige plucode.")
    sve =               fields.Char('sve', help="Standaard verpakkings eenheid bij leverancier.")
    status =            fields.Char('status', help="Mogelijke waarden: Actief/Non Actief/Gesaneerd")
    keurmerkbio =       fields.Char('keurmerkbio', help="keurmerkbio")
    keurmerkoverig =    fields.Char('keurmerkoverig', help="keurmerkoverig")
    herkomstregio =     fields.Char('herkomstregio', help="herkokmstregio")
    dieetinformatie =   fields.Char('dieetinformatie', help="0 = onbekend / 1 = aanwezig / 2 = niet aanwezig / 3 = mogelijk aanwezig")
    aantaldagenhoudbaar=fields.Char('aantaldagenhoudbaar', help="aantaldagenhoudbaar")
    bewaartemperatuur = fields.Char('bewaartemperatuur', help="bewaartemperatuur")
    gebruikstips =      fields.Char('gebruikstips', help="gebruikstips")
    lengte =            fields.Char('lengte', help="lengte")
    breedte =           fields.Char('breedte', help="breedte")
    hoogte =            fields.Char('hoogte', help="hoogte")
    code =              fields.Char('code', help="code")
    d204 =              fields.Char('d204', help="Cacao")
    d209 =              fields.Char('d209', help="Glutamaat")
    d210 =              fields.Char('d210', help="Gluten")
    d212 =              fields.Char('d212', help="Ei")
    d213 =              fields.Char('d213', help="Kip")
    d214 =              fields.Char('d214', help="Melk")
    d234 =              fields.Char('d234', help="Koriander")
    d215 =              fields.Char('d215', help="Lactose")
    d239 =              fields.Char('d239', help="Lupine")
    d216 =              fields.Char('d216', help="Mais")
    d217 =              fields.Char('d217', help="Noten")
    d217b =             fields.Char('d217b', help="Notenolie")
    d220 =              fields.Char('d220', help="Peulvruchten")
    d221 =              fields.Char('d221', help="Pinda")
    d221b =             fields.Char('d221b', help="Pindaolie")
    d222 =              fields.Char('d222', help="Rogge")
    d223 =              fields.Char('d223', help="Rundvlees")
    d236 =              fields.Char('d236', help="Schaaldieren")
    d235 =              fields.Char('d235', help="Selderij")
    d238 =              fields.Char('d238', help="Sesam")
    d238b =             fields.Char('d238b', help="Sesamolie")
    d225 =              fields.Char('d225', help="Soja")
    d226 =              fields.Char('d226', help="Soja-olie")
    d228 =              fields.Char('d228', help="Sulfiet")
    d230 =              fields.Char('d230', help="Tarwe")
    d232 =              fields.Char('d232', help="Varkensvlees")
    d237 =              fields.Char('d237', help="Vis")
    d240 =              fields.Char('d240', help="Wortel")
    d241 =              fields.Char('d241', help="Mosterd")
    d242 =              fields.Char('d242', help="Weekdieren")

    
    @api.one
    def _compute_inkoopprijs(self):
        try:
            self.inkoopprijs = self.seller_ids[0].inkoopprijs
        except:
            _logger.warning("Could not set inkoopprijs")

    @api.one        
    def _compute_bestelnummer(self):
        try:
            self.bestelnummer = self.seller_ids[0].bestelnummer
        except:
            _logger.warning("Could not set bestelnummer")

    @api.one       
    def _compute_consumentenprijs(self):
        try:
            self.consumentenprijs = self.seller_ids[0].consumentenprijs
        except:
            _logger.warning("Could not set consumentenprijs")

    
